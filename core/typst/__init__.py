# -*- coding: utf-8 -*-
"""Typst 本地排版。

排版方案移植自 ``astrbot_plugin_blue_protocol``（MIT，Copyright (c) 2026 uuutt）：

* 编译器跑在**独立子进程**（超时即回收），主进程不会被卡住；
* 卡片参数通过 ``data.json`` 交给模板，模板不执行任何外部代码；
* 字体只从插件 data 目录与系统字体取，必要时按固定来源下载中文字体。

对外只暴露 :func:`render_card` 与 :func:`status`。
"""

from __future__ import annotations

from .render import (
    DEFAULT_PPI,
    DEFAULT_TIMEOUT,
    TypstRenderError,
    render_card,
    shot_dir,
    status,
)

__all__ = [
    "DEFAULT_PPI",
    "DEFAULT_TIMEOUT",
    "TypstRenderError",
    "render_card",
    "shot_dir",
    "status",
]
