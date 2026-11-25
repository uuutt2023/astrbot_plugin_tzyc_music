# -*- coding: utf-8 -*-
"""Typst 隔离编译进程。

参考 SXP-Simon/astrbot_plugin_qq_group_daily_analysis 的做法：编译器跑在
**独立子进程**里（``python -I worker.py <job_dir>``），这样模板写错、字体炸了
或者排版卡住都只会让子进程退出，不会拖垮 AstrBot 主进程；主进程侧再套一层
超时，超时后直接回收子进程。

这个文件**不导入 astrbot**，也不执行公告正文里的任何代码——正文以 JSON 字符串
的形式交给 Typst 模板。
"""

from __future__ import annotations

import io
import json
import math
import sys
from pathlib import Path
from xml.etree import ElementTree

# 版心宽度（逻辑像素）。长图 390px、卡片 800px，都按 144 PPI 栅格化。
REPORT_PPI = 144
MAX_WIDTH_PX = 1410
MAX_HEIGHT_PX = 30000
MAX_PIXELS = 40_000_000
MAX_PNG_BYTES = 32 * 1024 * 1024


def _custom_page_size(svg: bytes) -> tuple[float, float]:
    """从矢量导出结果里读真实画布尺寸（不信任模板自己声明的尺寸）。"""
    if not isinstance(svg, bytes):
        raise RuntimeError("Typst 模板必须生成单张静态长图，不能分页")
    try:
        with io.BytesIO(svg) as stream:
            _, root = next(ElementTree.iterparse(stream, events=("start",)))
            _, _, width, height = (
                float(value) for value in root.attrib["viewBox"].split()
            )
        return width, height
    except (ElementTree.ParseError, KeyError, ValueError, StopIteration) as error:
        raise RuntimeError("无法读取 Typst 模板的实际画布尺寸") from error


def _check_canvas(compiler, raster_ppi: int) -> tuple[float, float, int]:
    """测量真实版心并校验像素预算，超长图逐档回落导出密度。"""
    from typst import TypstError

    if type(raster_ppi) is not int or raster_ppi < 72 or raster_ppi > 300:
        raise RuntimeError("Typst 导出密度超出允许范围")
    try:
        svg = compiler.compile(format="svg")
        point_width, point_height = _custom_page_size(svg)
    except TypstError as error:
        raise RuntimeError(getattr(error, "diagnostic", str(error))) from error
    pixel_width = point_width * raster_ppi / 72
    pixel_height = point_height * raster_ppi / 72
    if not all(
        math.isfinite(value) and value > 0 for value in (pixel_width, pixel_height)
    ):
        raise RuntimeError("Typst 画布尺寸无效")
    if pixel_height > MAX_HEIGHT_PX or pixel_width * pixel_height > MAX_PIXELS:
        raise RuntimeError("Typst 长图超过单图像素预算，请减少内容或降低导出密度")
    for candidate in (raster_ppi, 144, 120, 96):
        if candidate > raster_ppi:
            continue
        scale = candidate / raster_ppi
        width = math.ceil(pixel_width * scale)
        height = math.ceil(pixel_height * scale)
        if (
            width <= MAX_WIDTH_PX
            and height <= MAX_HEIGHT_PX
            and width * height <= MAX_PIXELS
        ):
            return point_width, point_height, candidate
    raise RuntimeError("Typst 长图超过单图像素预算")


def compile_job(job_dir: Path, raster_ppi: int = REPORT_PPI) -> int:
    """编译任务目录里的 ``main.typ``，输出 ``report.png``。

    Returns:
        实际使用的导出密度（PPI）。
    """
    try:
        import typst
    except ImportError as exc:
        raise RuntimeError("未安装 typst 依赖，请在插件依赖里勾选 typst") from exc

    config_path = job_dir / "typst.json"
    config = {}
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    font_paths = [str(p) for p in config.get("font_paths") or []]
    include_system = bool(config.get("include_system_fonts", True))

    fonts = typst.Fonts(
        include_system_fonts=include_system,
        font_paths=font_paths,
    )
    families = list(fonts.families())
    lowered = " ".join(families).lower()
    if not any(
        hint in lowered
        for hint in (
            "noto sans cjk",
            "noto sans sc",
            "noto sans tc",
            "source han",
            "pingfang",
            "microsoft yahei",
            "wenquanyi",
            "simhei",
            "simsun",
        )
    ):
        raise RuntimeError(
            "Typst 缺少中文字体：系统里没找到中文字族，"
            "请检查插件数据目录 typst/fonts/ 或在配置里指定字体下载地址"
        )

    compiler = typst.Compiler(
        str(job_dir / "main.typ"),
        root=str(job_dir),
        font_paths=fonts,
        ignore_system_fonts=not include_system,
    )
    _point_w, _point_h, ppi = _check_canvas(compiler, raster_ppi)
    output = job_dir / "report.png"
    compiler.compile(output=str(output), format="png", ppi=ppi)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Typst 没有产出图片")
    if output.stat().st_size > MAX_PNG_BYTES:
        raise RuntimeError("Typst 产出的图片超过 32 MiB")
    return ppi


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("用法：worker.py <job_dir> [--ppi N]\n")
        return 2
    job_dir = Path(argv[1])
    ppi = REPORT_PPI
    if "--ppi" in argv:
        try:
            ppi = int(argv[argv.index("--ppi") + 1])
        except (IndexError, ValueError):
            sys.stderr.write("--ppi 需要一个整数\n")
            return 2
    try:
        compile_job(job_dir, ppi)
    except Exception as error:  # noqa: BLE001
        sys.stderr.write(f"Typst 编译失败：{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
