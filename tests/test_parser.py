"""网易云链接解析 + 自动解析事件的行为测试。

解析层是本插件自己写的（core/ncm_parser.py），行为参考
astrbot_plugin_media_parser，但代码不共享。
"""

import unittest

from .support import parser_module


class ParserTests(unittest.TestCase):
    def extract(self, text):
        return [(link.kind, link.ident) for link in parser_module.extract_links(text)]

    def test_extracts_plain_song_link(self):
        self.assertEqual(
            self.extract("https://music.163.com/song?id=347230"),
            [("song", "347230")],
        )

    def test_extracts_hash_route_link(self):
        # 网易云分享短链就是这种形态
        self.assertEqual(
            self.extract("分享给好友：https://music.163.com/#/song?id=1973665667"),
            [("song", "1973665667")],
        )

    def test_extracts_mobile_and_playlist_links(self):
        self.assertEqual(
            self.extract("https://m.music.163.com/m/song?id=347230"),
            [("song", "347230")],
        )
        self.assertEqual(
            self.extract("https://music.163.com/playlist?id=3778678"),
            [("playlist", "3778678")],
        )

    def test_accepts_scheme_less_forms(self):
        self.assertEqual(
            self.extract("//music.163.com/song?id=347230"),
            [("song", "347230")],
        )
        self.assertEqual(
            self.extract("music.163.com/song?id=347230"),
            [("song", "347230")],
        )

    def test_strips_trailing_punctuation(self):
        self.assertEqual(
            self.extract("看看这个 https://music.163.com/song?id=347230。"),
            [("song", "347230")],
        )
        self.assertEqual(
            self.extract("(https://music.163.com/song?id=347230)"),
            [("song", "347230")],
        )

    def test_deduplicates_and_keeps_order(self):
        text = (
            "https://music.163.com/song?id=1 和 https://music.163.com/song?id=2 "
            "还有 https://music.163.com/song?id=1"
        )
        self.assertEqual(self.extract(text), [("song", "1"), ("song", "2")])

    def test_rejects_foreign_hosts_and_lookalikes(self):
        # 伪造域名：evil.com 下的 music.163.com 路径
        self.assertEqual(self.extract("https://evil.com/music.163.com/song?id=1"), [])
        # 其它站点
        self.assertEqual(self.extract("https://www.163.com/song?id=1"), [])
        # 主机名前缀攻击
        self.assertEqual(self.extract("https://music.163.com.evil.net/song?id=1"), [])

    def test_rejects_unsupported_paths(self):
        self.assertEqual(self.extract("https://music.163.com/album?id=1"), [])
        self.assertEqual(self.extract("https://music.163.com/mv?id=1"), [])
        self.assertEqual(self.extract("https://music.163.com/user/home?id=1"), [])

    def test_rejects_bad_identifiers(self):
        self.assertEqual(self.extract("https://music.163.com/song?id=0"), [])
        self.assertEqual(self.extract("https://music.163.com/song?id=abc"), [])
        self.assertEqual(self.extract("https://music.163.com/song?id="), [])
        self.assertEqual(self.extract("https://music.163.com/song?id=01"), [])
        # 多个 id 参数不认
        self.assertEqual(self.extract("https://music.163.com/song?id=1&id=2"), [])

    def test_rejects_credentials_and_bad_ports(self):
        self.assertEqual(self.extract("https://user:pw@music.163.com/song?id=1"), [])
        self.assertEqual(self.extract("https://music.163.com:8443/song?id=1"), [])
        self.assertEqual(self.extract("https://music.163.com:99999/song?id=1"), [])

    def test_accepts_default_ports(self):
        self.assertEqual(
            self.extract("http://music.163.com:80/song?id=1"), [("song", "1")]
        )
        self.assertEqual(
            self.extract("https://music.163.com:443/song?id=1"), [("song", "1")]
        )

    def test_rejects_host_prefix_confusion(self):
        # 主机名以官方域名开头但属于别的站点
        self.assertEqual(self.extract("https://music.163.com.evil.net/song?id=1"), [])
        self.assertEqual(self.extract("https://notmusic.163.com/song?id=1"), [])
        self.assertEqual(self.extract("https://xmusic.163.com/song?id=1"), [])
        # 官方域名出现在路径里
        self.assertEqual(self.extract("https://evil.net/x/music.163.com/song?id=1"), [])

    def test_rejects_non_http_scheme(self):
        self.assertEqual(self.extract("ftp://music.163.com/song?id=1"), [])
        self.assertEqual(self.extract("javascript:music.163.com/song?id=1"), [])

    def test_allows_extra_query_params(self):
        self.assertEqual(
            self.extract("https://music.163.com/song?id=347230&userid=123"),
            [("song", "347230")],
        )

    def test_mobile_domains(self):
        self.assertEqual(
            self.extract("https://m.music.163.com/m/song?id=1"), [("song", "1")]
        )
        self.assertEqual(
            self.extract("https://y.music.163.com/m/playlist?id=2"), [("playlist", "2")]
        )

    def test_plain_text_has_no_link(self):
        self.assertEqual(self.extract("今天天气不错"), [])
        self.assertEqual(self.extract(""), [])
        self.assertEqual(self.extract("music.163.com"), [])

    def test_contains_link_helper(self):
        self.assertTrue(parser_module.contains_link("https://music.163.com/song?id=1"))
        self.assertFalse(parser_module.contains_link("今天天气不错"))

    def test_extract_song_ids_skips_playlists(self):
        text = "https://music.163.com/song?id=11 https://music.163.com/playlist?id=22"
        self.assertEqual(parser_module.extract_song_ids(text), ["11"])

    def test_normalized_url(self):
        link = parser_module.extract_links("https://music.163.com/song?id=347230")[0]
        self.assertEqual(link.url, "https://music.163.com/song?id=347230")

    def test_html_escaped_ampersand(self):
        # &amp; 是 HTML 转义后的 &
        self.assertEqual(
            self.extract("https://music.163.com/song?id=347230&amp;x=1"),
            [("song", "347230")],
        )


if __name__ == "__main__":
    unittest.main()
