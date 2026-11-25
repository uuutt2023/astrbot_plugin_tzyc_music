# -*- coding: utf-8 -*-
"""Typst 字体解析：受管理目录 → 系统字体 → 自动下载。

参考 SXP-Simon/astrbot_plugin_qq_group_daily_analysis 的 Typst 字体方案：
字体只从**插件 data 目录**和**系统字体**里取，下载目标固定，不接受任意路径。

中文公告正文必须有中文字体，否则 Typst 会渲染成空白或豆腐块，所以这里的
解析顺序是：受管理目录（有则只用它，保证排版稳定）→ 系统字体（扫到中文字族就用）
→ 都没有时按固定来源下载 Noto Sans SC 到受管理目录。
"""

from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path

FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}

# 能显示简体中文的字族名（小写匹配）
CJK_HINTS = (
    "noto sans cjk sc",
    "noto sans sc",
    "noto sans tc",
    "noto serif cjk sc",
    "noto serif sc",
    "source han sans",
    "source han serif",
    "pingfang",
    "microsoft yahei",
    "wenquanyi",
    "wqy",
    "simhei",
    "simsun",
    "heiti",
    "droid sans fallback",
)

# 固定上游，不接受用户自定义目标路径；URL 里的方括号要转义
DEFAULT_FONT_URLS = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/"
    "NotoSansSC%5Bwght%5D.ttf",
    "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/"
    "NotoSansSC%5Bwght%5D.ttf",
)

MAX_FONT_BYTES = 48 * 1024 * 1024
_FONT_MAGIC = (b"ttcf", b"OTTO", b"\x00\x01\x00\x00", b"true")


def managed_dir(data_dir: Path) -> Path:
    """插件受管理字体目录。"""
    return data_dir / "typst" / "fonts"


def list_fonts(directory: Path) -> list[str]:
    """目录里的字体文件名（按名字排序）。"""
    if not directory.is_dir():
        return []
    return sorted(
        p.name
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in FONT_SUFFIXES
    )


def has_cjk_family(families) -> bool:  # noqa: ANN001
    """字族列表里有没有能显示中文的。"""
    for name in families:
        low = str(name).lower()
        if any(hint in low for hint in CJK_HINTS):
            return True
    return False


def pick_cjk_family(families) -> str | None:  # noqa: ANN001
    """从字族列表里挑一个能显示中文的，返回字体名。"""
    for name in families:
        low = str(name).lower()
        if any(hint in low for hint in CJK_HINTS):
            return str(name)
    return None


def system_families() -> list[str]:
    """系统字体字族列表；typst 没装时返回空。"""
    try:
        import typst
    except ImportError:
        return []
    # 不同 typst-py 版本的 font_paths 默认值不一样（None 会直接抛错），
    # 这里两种写法都试一遍。
    for kwargs in (
        {"include_system_fonts": True, "font_paths": []},
        {"include_system_fonts": True},
    ):
        try:
            fonts = typst.Fonts(**kwargs)
            families = list(fonts.families())
        except Exception:  # noqa: BLE001
            continue
        if families:
            return families
    return []


def resolve(data_dir: Path) -> dict:
    """决定这次编译用什么字体。

    Returns:
        ``{"font_paths": [...], "include_system_fonts": bool, "has_cjk": bool,
        "source": "managed"|"system"|"none"}``
    """
    directory = managed_dir(data_dir)
    managed = list_fonts(directory)
    if managed:
        return {
            "font_paths": [str(directory)],
            "include_system_fonts": False,
            "has_cjk": True,  # 受管理目录里的字体由 ensure_cjk_font 保证是中文的
            "family": managed_family(directory),
            "source": "managed",
        }
    families = system_families()
    family = pick_cjk_family(families)
    if family:
        return {
            "font_paths": [],
            "include_system_fonts": True,
            "has_cjk": True,
            "family": family,
            "source": "system",
        }
    return {
        "font_paths": [],
        "include_system_fonts": True,
        "has_cjk": False,
        "family": "",
        "source": "none",
    }


def managed_family(directory: Path) -> str:
    """受管理字体目录里的中文字族名（读不到就退回默认名）。"""
    try:
        import typst

        fonts = typst.Fonts(include_system_fonts=False, font_paths=[str(directory)])
        family = pick_cjk_family(list(fonts.families()))
        if family:
            return family
    except Exception:  # noqa: BLE001
        pass
    return "Noto Sans SC"


def _looks_like_font(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    return any(head.startswith(magic) for magic in _FONT_MAGIC)


def download_cjk_font(data_dir: Path, url: str | None = None) -> Path | None:
    """把中文字体下载到受管理目录，返回字体路径。

    ``url`` 为空时按 :data:`DEFAULT_FONT_URLS` 依次尝试；全部失败返回 ``None``。
    下载走临时文件 + 原子替换，中途失败不会留下半个字体。
    """
    directory = managed_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "NotoSansSC.ttf"
    if target.is_file() and target.stat().st_size > 1024:
        return target

    urls = [url] if url else list(DEFAULT_FONT_URLS)
    for source in urls:
        if not source:
            continue
        tmp_path: Path | None = None
        try:
            with urllib.request.urlopen(source, timeout=120) as resp:  # noqa: S310
                fd, tmp_name = tempfile.mkstemp(dir=str(directory), suffix=".part")
                tmp_path = Path(tmp_name)
                size = 0
                with open(fd, "wb") as out:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_FONT_BYTES:
                            raise ValueError("字体文件过大")
                        out.write(chunk)
            if size < 1024 or not _looks_like_font(tmp_path):
                raise ValueError("下载内容不是有效字体")
            tmp_path.replace(target)
            return target
        except Exception:  # noqa: BLE001 - 换下一个来源
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            continue
    return None


def ensure_cjk_font(data_dir: Path, url: str | None = None) -> Path | None:
    """确保有可用的中文字体：受管理目录 → 系统 → 下载。"""
    directory = managed_dir(data_dir)
    if list_fonts(directory):
        return directory
    if has_cjk_family(system_families()):
        return None  # 用系统字体即可
    return download_cjk_font(data_dir, url)


def ensure_font_config(data_dir: Path, url: str | None = None) -> dict:
    """保证有中文字体可用，并返回编译用的字体配置。

    受管理目录已有字体时只用受管理字体（排版稳定）；否则用系统字体；
    两者都没有时按固定来源下载中文字体。
    """
    state = resolve(data_dir)
    if state["has_cjk"]:
        return state
    downloaded = download_cjk_font(data_dir, url)
    if downloaded is not None:
        return resolve(data_dir)
    return state


def font_summary(data_dir: Path) -> dict:
    """给面板展示用的字体状态。"""
    directory = managed_dir(data_dir)
    managed = list_fonts(directory)
    families = system_families()
    return {
        "directory": str(directory),
        "managed": managed,
        "managed_count": len(managed),
        "system_cjk": has_cjk_family(families),
        "source": "managed"
        if managed
        else ("system" if has_cjk_family(families) else "none"),
    }


def cleanup_temp(data_dir: Path) -> None:
    """清掉遗留的下载临时文件。"""
    directory = managed_dir(data_dir)
    if not directory.is_dir():
        return
    for item in directory.glob("*.part"):
        try:
            item.unlink()
        except OSError:
            pass


def disk_usage(data_dir: Path) -> int:
    """受管理字体目录占用字节数。"""
    directory = managed_dir(data_dir)
    if not directory.is_dir():
        return 0
    return sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
