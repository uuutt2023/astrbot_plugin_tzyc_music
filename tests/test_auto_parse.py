"""自动解析事件 + Typst 排版卡片的集成测试。

这些测试不联网：用假的服务端和假的图片数据驱动整条链路。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from .support import Config, Event, StarTools, api_module, main_module


class AutoParseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.cfg = Config(
            ncm_api_external_enabled=True,
            ncm_api_base="http://external.invalid",
            ncm_web_enabled=False,
            send_play_card=False,
            send_comment_card=False,
            send_lyrics_forward=False,
            load_mode="file",
            typst_enabled=False,
        )
        with patch.object(StarTools, "get_data_dir", return_value=self.data):
            self.plugin = main_module.NcmPlayerPlugin(None, self.cfg)
        self.addAsyncCleanup(self.plugin.terminate)

    async def test_song_link_renders_card(self):
        song = api_module.Song(
            id=347230,
            name="海阔天空",
            artists="Beyond",
            album="乐与怒",
            duration=324000,
        )
        self.plugin.api.fetch_song_detail = AsyncMock(return_value=song)
        self.plugin.api.fetch_bytes = AsyncMock(return_value=None)
        self.plugin._render_playing_card = AsyncMock(return_value="/tmp/card.png")

        event = Event()
        event.message_str = "分享 https://music.163.com/song?id=347230"
        await self.plugin.auto_parse(event)

        self.plugin.api.fetch_song_detail.assert_awaited_once_with(347230)
        self.plugin._render_playing_card.assert_awaited_once()
        # 一张卡片图 + 一段文字说明
        self.assertEqual(len(event.messages), 2)

    async def test_playlist_link_renders_selection(self):
        songs = [
            api_module.Song(id=1, name="甲", artists="歌手甲", duration=1000),
            api_module.Song(id=2, name="乙", artists="歌手乙", duration=2000),
        ]
        self.plugin.api.fetch_playlist = AsyncMock(return_value=("热歌榜", songs))
        self.plugin.api.fetch_bytes = AsyncMock(return_value=None)
        self.plugin._render_selection_card = AsyncMock(return_value="/tmp/list.png")

        event = Event()
        event.message_str = "https://music.163.com/playlist?id=3778678"
        await self.plugin.auto_parse(event)

        self.plugin.api.fetch_playlist.assert_awaited_once()
        self.plugin._render_selection_card.assert_awaited_once()
        self.assertEqual(len(event.messages), 1)

    async def test_no_link_is_ignored(self):
        event = Event()
        event.message_str = "今天天气不错"
        await self.plugin.auto_parse(event)
        self.assertEqual(event.messages, [])

    async def test_disabled_by_config(self):
        self.cfg["auto_parse_enabled"] = False
        event = Event()
        event.message_str = "https://music.163.com/song?id=347230"
        await self.plugin.auto_parse(event)
        self.assertEqual(event.messages, [])

    async def test_command_prefix_is_ignored(self):
        event = Event()
        event.message_str = "/点歌 https://music.163.com/song?id=347230"
        await self.plugin.auto_parse(event)
        self.assertEqual(event.messages, [])

    async def test_invalid_link_reports_failure(self):
        self.plugin.api.fetch_song_detail = AsyncMock(return_value=None)
        event = Event()
        event.message_str = "https://music.163.com/song?id=999999999"
        await self.plugin.auto_parse(event)
        self.assertEqual(len(event.messages), 1)
        self.assertIn("失效", str(event.messages[0]))

    async def test_keyword_handler_skips_messages_with_link(self):
        """带链接的消息交给自动解析，关键词监听不重复响应。"""
        event = Event()
        event.message_str = "我要听 https://music.163.com/song?id=347230"
        with patch.object(
            self.plugin, "_search_and_render", new_callable=AsyncMock
        ) as search:
            await self.plugin.listen_keyword(event)
        search.assert_not_awaited()

    async def test_llm_tool_skips_messages_with_link(self):
        event = Event()
        event.message_str = "https://music.163.com/song?id=347230"
        result = await self.plugin.search_songs(event, "海阔天空")
        self.assertIn("链接", result)


class TypstFallbackTests(unittest.IsolatedAsyncioTestCase):
    """Typst 优先、失败回落 Pillow。"""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.cfg = Config(
            ncm_api_external_enabled=True,
            ncm_api_base="http://external.invalid",
            ncm_web_enabled=False,
            typst_enabled=True,
        )
        with patch.object(StarTools, "get_data_dir", return_value=self.data):
            self.plugin = main_module.NcmPlayerPlugin(None, self.cfg)
        self.addAsyncCleanup(self.plugin.terminate)

    async def test_falls_back_to_pillow_when_typst_fails(self):
        song = api_module.Song(id=1, name="歌", artists="人", album="碟", duration=1000)
        self.plugin.typst.available = lambda: True
        self.plugin.typst.render_playing = AsyncMock(side_effect=RuntimeError("boom"))
        self.plugin.renderer.render_playing = MagicMock(return_value="/tmp/pil.png")
        path = await self.plugin._render_playing_card(song, None, "无损", "")
        self.assertEqual(path, "/tmp/pil.png")

    async def test_uses_typst_when_available(self):
        song = api_module.Song(id=1, name="歌", artists="人", album="碟", duration=1000)
        self.plugin.typst.available = lambda: True
        self.plugin.typst.render_playing = AsyncMock(return_value="/tmp/typst.png")
        path = await self.plugin._render_playing_card(song, None, "无损", "")
        self.assertEqual(path, "/tmp/typst.png")
        self.plugin.typst.render_playing.assert_awaited_once()

    async def test_pillow_used_when_typst_disabled(self):
        song = api_module.Song(id=1, name="歌", artists="人", album="碟", duration=1000)
        self.cfg["typst_enabled"] = False
        self.plugin.typst.available = lambda: True
        self.plugin.typst.render_playing = AsyncMock()
        self.plugin.renderer.render_playing = MagicMock(return_value="/tmp/pil.png")
        path = await self.plugin._render_playing_card(song, None, "无损", "")
        self.assertEqual(path, "/tmp/pil.png")
        self.plugin.typst.render_playing.assert_not_awaited()

    async def test_pillow_used_when_typst_unavailable(self):
        song = api_module.Song(id=1, name="歌", artists="人", album="碟", duration=1000)
        self.plugin.typst.available = lambda: False
        self.plugin.typst.render_playing = AsyncMock()
        self.plugin.renderer.render_playing = MagicMock(return_value="/tmp/pil.png")
        path = await self.plugin._render_playing_card(song, None, "无损", "")
        self.assertEqual(path, "/tmp/pil.png")
        self.plugin.typst.render_playing.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
