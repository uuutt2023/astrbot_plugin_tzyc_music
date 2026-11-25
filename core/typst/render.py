# -*- coding: utf-8 -*-
"""Typst 本地排版：把卡片数据编译成图片。

排版方案移植自 ``astrbot_plugin_blue_protocol``（MIT）：

* 编译器（``typst`` PyPI 包，内置 Rust Typst）跑在**独立子进程**里，带超时回收；
* 卡片文案与参数都通过 ``data.json`` 传进模板，模板不执行任何外部代码；
* 字体只从插件 data 目录和系统字体取，必要时按固定来源下载中文字体；
* 先矢量导出量真实画布，校验像素预算后再栅格化，超长图逐档回落密度。

相比原来的「PIL 直接画」，Typst 负责的是**排版**：文字换行、行距、层叠、
圆角、渐变这些交给排版引擎，排出来的字比 PIL 手搓的基线更整齐。

与上游的差别：那边还要把公告正文 HTML 拆成块，这里只有固定结构的卡片，
所以不需要 HTML 解析层；图片素材（封面、磁盘、头像）由调用方给到本地文件。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import fonts

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "typst"
_WORKER = Path(__file__).resolve().parent / "worker.py"

DEFAULT_PPI = 144
DEFAULT_TIMEOUT = 60.0
MAX_BYTES = 2_500_000


class TypstRenderError(RuntimeError):
    """Typst 排版失败（字体缺失、模板出错、超时等）。"""


# ---------------------------------------------------------------------------
# 缓存路径
# ---------------------------------------------------------------------------


def shot_dir(data_dir: Path) -> Path:
    d = Path(data_dir) / "typst_shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(data_dir: Path, key: str) -> Path:
    h = hashlib.md5(str(key).encode()).hexdigest()
    return shot_dir(data_dir) / f"typst_{h}.jpg"


def _template_fingerprint(template: str) -> str:
    """模板内容的指纹。

    缓存键必须带上它：改了 ``.typ`` 模板（比如调版式、改配色）之后，
    同样的歌名/关键词还会命中旧图，卡片就会停留在旧版式上。
    """
    digest = hashlib.md5()
    digest.update(template.encode())
    for path in sorted(_TEMPLATE_DIR.glob("*.typ")):
        digest.update(path.name.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()


def _images_fingerprint(images: dict[str, Path]) -> str:
    """图片素材的指纹（按文件名 + 内容哈希）。

    封面变了、CD 素材重画了，缓存也得跟着失效。
    """
    digest = hashlib.md5()
    for name in sorted(images):
        digest.update(name.encode())
        source = images[name]
        try:
            if source and Path(source).is_file():
                digest.update(hashlib.md5(Path(source).read_bytes()).digest())
        except OSError:
            continue
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 任务目录
# ---------------------------------------------------------------------------


def _write_job(
    template: str,
    data: dict[str, Any],
    images: dict[str, Path],
) -> Path:
    """组装一次编译用的任务目录。"""
    if not _TEMPLATE_DIR.is_dir():
        raise TypstRenderError(f"Typst 模板目录缺失：{_TEMPLATE_DIR}")
    job_dir = Path(tempfile.mkdtemp(prefix="ncm_typst_"))
    for typ in _TEMPLATE_DIR.glob("*.typ"):
        shutil.copyfile(typ, job_dir / typ.name)
    # main.typ 就是模板本体：#import 只取引用，不会把模块内容排进页面。
    shutil.copyfile(_TEMPLATE_DIR / f"{template}.typ", job_dir / "main.typ")
    (job_dir / "data.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    for name, source in images.items():
        if source and Path(source).is_file():
            shutil.copyfile(source, job_dir / name)
    return job_dir


# ---------------------------------------------------------------------------
# 编译
# ---------------------------------------------------------------------------


async def _compile(job_dir: Path, ppi: int, timeout: float, font_config: dict) -> None:
    """跑隔离编译进程。"""
    (job_dir / "typst.json").write_text(
        json.dumps(font_config, ensure_ascii=False), encoding="utf-8"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(_WORKER),
        str(job_dir),
        "--ppi",
        str(ppi),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(timeout):
            _, stderr = await process.communicate()
    except TimeoutError as error:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await asyncio.gather(process.wait(), return_exceptions=True)
        raise TypstRenderError(
            f"Typst 排版超过 {timeout:.0f} 秒预算，已终止"
        ) from error
    if process.returncode:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        raise TypstRenderError(detail or f"Typst 编译进程退出码 {process.returncode}")
    output = job_dir / "report.png"
    if not output.is_file() or output.stat().st_size == 0:
        raise TypstRenderError("Typst 没有产出图片")


def _to_jpeg(source: Path, target: Path, quality: int) -> Path:
    """PNG 转 JPEG（平台更友好、体积更小）。Pillow 不可用时原样保留 PNG。"""
    try:
        from PIL import Image
    except ImportError:
        return source
    with Image.open(source) as im:
        im.convert("RGB").save(target, format="JPEG", quality=quality, optimize=True)
    return target


def _shrink_to_budget(path: Path, max_bytes: int) -> None:
    """超出字节预算时降质/缩放。"""
    if max_bytes <= 0 or path.stat().st_size <= max_bytes:
        return
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as im:
        src = im.convert("RGB")
    for quality, scale in ((78, 1.0), (72, 0.75), (66, 0.5), (60, 0.35)):
        img = (
            src
            if scale == 1.0
            else src.resize(
                (max(1, int(src.width * scale)), max(1, int(src.height * scale))),
                Image.LANCZOS,
            )
        )
        img.save(path, format="JPEG", quality=quality, optimize=True)
        if path.stat().st_size <= max_bytes:
            return


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


async def render_card(
    template: str,
    data: dict[str, Any],
    images: dict[str, Path],
    data_dir: Path,
    *,
    ppi: int = DEFAULT_PPI,
    timeout: float = DEFAULT_TIMEOUT,
    quality: int = 88,
    max_bytes: int = MAX_BYTES,
    font_url: str | None = None,
    cache_key: str | None = None,
) -> Path:
    """用 Typst 排一张卡片，返回图片路径。

    Args:
        template: 模板名（``templates/typst/<template>.typ``）。
        data: 写进 ``data.json`` 的数据。
        images: 图片素材，键是模板里引用的文件名，值是本地路径。
        data_dir: 插件数据目录（字体缓存、输出缓存都放这里）。
    """
    key = (
        cache_key
        or f"{template}:{json.dumps(data, ensure_ascii=False, sort_keys=True)}"
    )
    # 缓存键带上模板和素材的指纹：改了版式或换了封面，旧图不能复用。
    key = (
        f"{key}|tpl:{_template_fingerprint(template)}|img:{_images_fingerprint(images)}"
    )
    cached = _cache_path(data_dir, key)
    if cached.is_file() and cached.stat().st_size > 0:
        return cached

    font_config = fonts.ensure_font_config(data_dir, font_url)
    if not font_config.get("has_cjk"):
        raise TypstRenderError("Typst 找不到中文字体，无法排版卡片")

    payload = dict(data)
    payload["font"] = font_config.get("family") or ""
    payload.setdefault("colors", {})

    job_dir = _write_job(template, payload, images)
    try:
        await _compile(job_dir, ppi, timeout, font_config)
        produced = job_dir / "report.png"
        staged = shot_dir(data_dir) / f".staged_{cached.stem}.jpg"
        converted = _to_jpeg(produced, staged, quality)
        _shrink_to_budget(converted, max_bytes)
        converted.replace(cached)
        return cached
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def status(data_dir: Path) -> dict[str, Any]:
    """Typst 排版可用状态（诊断命令用）。"""
    try:
        import typst  # noqa: F401

        available = True
    except ImportError:
        available = False
    summary = fonts.font_summary(data_dir)
    return {
        "available": available,
        "font_source": summary.get("source", "none"),
        "managed_fonts": summary.get("managed_count", 0),
        "system_cjk": summary.get("system_cjk", False),
    }
