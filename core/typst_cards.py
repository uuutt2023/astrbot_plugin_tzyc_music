# -*- coding: utf-8 -*-
"""Typst 排版的卡片渲染：选歌列表 / 播放卡片 / 热评卡片。

与 :mod:`core.renderer`（Pillow）渲染的是同一套视觉：

* 排版交给 Typst —— 文字基线、行距、圆角、渐变、层叠由排版引擎算，
  比 Pillow 手搓的基线整齐；
* CD 光盘和头像仍然用 Pillow 画（见 :func:`core.renderer.disc_png_bytes`），
  当成素材交给 Typst 摆位 —— 玻璃盘心那种效果在 Typst 里手搓不划算。

Typst 不可用（没装依赖 / 没有中文字体 / 编译失败）时由调用方回落到
Pillow 版本，功能不中断，只是排版引擎不同。
"""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .ncm_api import Comment, Song
from .renderer import avatar_png_bytes, disc_png_bytes, disc_with_shadow_png_bytes
from .typst import render as typst_render

# 与 core/renderer.py 保持一致的配色
COLORS = {
    "bg_top": "#F7F9FC",
    "bg_bottom": "#E8EDF4",
    "card": "#FFFFFF",
    "border": "#DEE3EB",
    "ink": "#1A1A1F",
    "muted": "#7A7F8A",
    "faint": "#A5AAB4",
    "accent": "#E12D3C",
}

# 三张卡的版式尺寸（单位：CSS 像素，和 Pillow 版一一对应）
SELECTION_STYLE = {
    "width": 780,
    "header_h": 96,
    "row_h": 116,
    "footer_h": 62,
    "pad": 22,
}
PLAYING_STYLE = {
    "width": 980,
    "height": 520,
    "pad": 36,
    "disc_size": 368,
}
COMMENT_STYLE = {
    "width": 780,
    "pad": 34,
    "body_size": 26,
    "line_h": 42,
    "avatar_size": 56,
}


class TypstCardRenderer:
    """把卡片数据交给 Typst 排版。"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    # ---------- 能力探测 ----------

    def available(self) -> bool:
        """Typst 能不能用（依赖装了 + 有中文字体）。"""
        if importlib.util.find_spec("typst") is None:
            return False
        source = typst_render.status(self.data_dir).get("font_source")
        return bool(source) and source != "none"

    # ---------- 内部 ----------

    async def _render(
        self,
        template: str,
        data: dict[str, Any],
        images: dict[str, bytes],
        *,
        ppi: int,
        timeout: float,
        quality: int,
        cache_key: str,
    ) -> str:
        work = Path(tempfile.mkdtemp(prefix="ncm_typst_img_"))
        try:
            paths: dict[str, Path] = {}
            for name, blob in images.items():
                target = work / name
                target.write_bytes(blob)
                paths[name] = target
            out = await typst_render.render_card(
                template,
                data,
                paths,
                self.data_dir,
                ppi=ppi,
                timeout=timeout,
                quality=quality,
                cache_key=cache_key,
            )
            return str(out)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ---------- 选歌列表 ----------

    async def render_selection(
        self,
        songs: list[Song],
        covers: list[bytes | None],
        keyword: str,
        *,
        ppi: int = 144,
        timeout: float = 60.0,
        quality: int = 88,
    ) -> str:
        rows = []
        images: dict[str, bytes] = {}
        for index, song in enumerate(songs):
            cover = covers[index] if index < len(covers) else None
            name = f"disc_{index}.png"
            images[name] = disc_png_bytes(cover, 92)
            sub = f"{song.artists} · {song.album}" if song.album else song.artists
            rows.append(
                {
                    "n": index + 1,
                    "name": song.name,
                    "sub": sub,
                    "duration": song.duration_str,
                    "disc": name,
                }
            )
        data = {
            "style": dict(SELECTION_STYLE, scale=72.0 / max(72, ppi)),
            "colors": dict(COLORS),
            "title": f"网易云点歌 · {keyword}",
            "rows": rows,
            "footer": "回复序号点歌，例如：1",
        }
        key = f"selection|{keyword}|{[s.id for s in songs]}|{ppi}"
        return await self._render(
            "selection",
            data,
            images,
            ppi=ppi,
            timeout=timeout,
            quality=quality,
            cache_key=key,
        )

    # ---------- 播放卡片 ----------

    async def render_playing(
        self,
        song: Song,
        cover: bytes | None,
        quality: str,
        vip: str = "",
        *,
        ppi: int = 144,
        timeout: float = 60.0,
        quality_jpeg: int = 88,
    ) -> str:
        if vip == "ok":
            tag = f"VIP · {quality}"
            tag_color = "accent"
        elif vip == "mirror":
            tag = f"VIP · {quality}"
            tag_color = "faint"
        else:
            tag = f"♪ {quality}"
            tag_color = "accent"
        meta = " · ".join(x for x in [song.album, song.duration_str] if x)
        disc_png, shadow_pad = disc_with_shadow_png_bytes(
            cover, PLAYING_STYLE["disc_size"]
        )
        data = {
            "style": dict(PLAYING_STYLE, scale=72.0 / max(72, ppi)),
            "colors": dict(COLORS),
            "name": song.name,
            "artists": song.artists,
            "meta": meta,
            "tag": tag,
            "tag_color": tag_color,
            "brand": "NetEase Cloud Music",
            "disc": "disc.png",
            "shadow_pad": shadow_pad,
        }
        images = {"disc.png": disc_png}
        key = f"playing|{song.id}|{quality}|{vip}|{ppi}"
        return await self._render(
            "playing",
            data,
            images,
            ppi=ppi,
            timeout=timeout,
            quality=quality_jpeg,
            cache_key=key,
        )

    # ---------- 热评卡片 ----------

    async def render_comment(
        self,
        comment: Comment,
        song: Song,
        avatar: bytes | None,
        *,
        ppi: int = 144,
        timeout: float = 60.0,
        quality: int = 88,
    ) -> str:
        data = {
            "style": dict(COMMENT_STYLE, scale=72.0 / max(72, ppi)),
            "colors": dict(COLORS),
            "content": comment.content,
            "nickname": comment.nickname,
            "liked": comment.liked_count,
            "source": f"来自《{song.name}》的网易云热评",
            "avatar": "avatar.png",
        }
        images = {"avatar.png": avatar_png_bytes(avatar, COMMENT_STYLE["avatar_size"])}
        key = f"comment|{song.id}|{comment.nickname}|{ppi}"
        return await self._render(
            "comment",
            data,
            images,
            ppi=ppi,
            timeout=timeout,
            quality=quality,
            cache_key=key,
        )


def typst_status(data_dir: Path) -> dict[str, Any]:
    """Typst 可用状态（诊断命令用）。"""
    return typst_render.status(Path(data_dir))
