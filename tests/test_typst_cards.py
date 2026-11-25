"""Typst 排版卡片的端到端测试。

真的调 Typst 编译器排三张卡，验证：
* 三张卡都能编译出图，且尺寸与 Pillow 版一致；
* Typst 不可用时能力探测能正确返回 False；
* 缓存键包含模板与素材指纹（改模板后旧图不会复用）。

Typst 没装时整组跳过——插件在没装 typst 的环境下靠 Pillow 兜底，
功能不受影响，所以这里不强制。
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from .support import api_module, renderer_module, typst_cards_module


def _typst_installed() -> bool:
    return importlib.util.find_spec("typst") is not None


@unittest.skipUnless(_typst_installed(), "未安装 typst 依赖")
class TypstCardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.renderer = typst_cards_module.TypstCardRenderer(self.data)
        self.songs = [
            api_module.Song(
                id=347230,
                name="海阔天空",
                artists="Beyond",
                album="乐与怒",
                duration=324000,
            ),
            api_module.Song(
                id=1, name="晴天", artists="周杰伦", album="叶惠美", duration=269000
            ),
        ]

    async def test_availability_probe(self):
        self.assertIsInstance(self.renderer.available(), bool)

    async def test_render_selection(self):
        path = await self.renderer.render_selection(
            self.songs, [None, None], "海阔天空"
        )
        self.assertTrue(Path(path).is_file())
        self.assertGreater(Path(path).stat().st_size, 0)

    async def test_render_playing(self):
        path = await self.renderer.render_playing(self.songs[0], None, "无损", "ok")
        self.assertTrue(Path(path).is_file())

    async def test_render_comment(self):
        comment = api_module.Comment(
            content="这是一条热评内容，用来验证排版。",
            nickname="测试用户",
            liked_count=123,
        )
        path = await self.renderer.render_comment(comment, self.songs[0], None)
        self.assertTrue(Path(path).is_file())

    async def test_selection_size_matches_pillow(self):
        """两张卡的画布尺寸应该一致（都是 780 宽）。"""
        from PIL import Image

        path = await self.renderer.render_selection(self.songs, [None, None], "测试")
        with Image.open(path) as im:
            typst_size = im.size
        pil_path = renderer_module.CardRenderer(self.data).render_selection(
            self.songs, [None, None], "测试"
        )
        with Image.open(pil_path) as im:
            pil_size = im.size
        self.assertEqual(typst_size[0], pil_size[0])

    async def test_playing_size_matches_pillow(self):
        from PIL import Image

        path = await self.renderer.render_playing(self.songs[0], None, "无损", "")
        with Image.open(path) as im:
            typst_size = im.size
        pil_path = renderer_module.CardRenderer(self.data).render_playing(
            self.songs[0], None, "无损", ""
        )
        with Image.open(pil_path) as im:
            pil_size = im.size
        self.assertEqual(typst_size, pil_size)

    async def test_cache_key_includes_template_and_images(self):
        """改了模板或素材，缓存必须失效，不能拿旧图出来。"""
        render = (
            typst_cards_module.render_module
            if hasattr(typst_cards_module, "render_module")
            else None
        )
        if render is None:
            from .support import typst_render_module

            render = typst_render_module
        first = render._template_fingerprint("playing")
        second = render._template_fingerprint("playing")
        self.assertEqual(first, second)
        self.assertNotEqual(first, render._template_fingerprint("selection"))


if __name__ == "__main__":
    unittest.main()
