# -*- coding: utf-8 -*-
"""网易云音乐链接识别与解析。

用户丢一条分享链接过来，插件就能直接把歌曲/歌单渲染成卡片发回去。

**这是本插件自己写的实现**：参考了 ``astrbot_plugin_media_parser`` 的*行为*
（监听所有消息 → 找出链接 → 解析 → 出图），但没有复制它的代码——那个插件是
AGPL-3.0，本插件是 MIT，代码不能混。识别规则和支持范围如下：

* 只认网易云音乐官方域名 ``music.163.com``（含移动端 ``m.`` / ``y.``），
  不解析第三方镜像站的链接；
* 支持单曲（``/song``、``/m/song``）和歌单（``/playlist``、``/m/playlist``），
  专辑（``/album``）与 mv（``/mv``）暂不支持；
* ``#`` 之后的哈希路由（``music.163.com/#/song?id=1``）也认，网易云分享
  出来的短链基本都是这种形态；
* 主机、端口、编号都做严格校验，避免把 ``evil.com/music.163.com``
  这类伪造链接当成真链接。

实现思路是**一条正则直接定位「官方域名 + 支持的路径 + id 参数」**：
不匹配的链接压根不会进入后续处理，因此伪造域名、主机名前缀攻击、带凭据的
URL、非法端口、非法编号全部在同一步被挡掉。

链接只从消息文本里提取，不下载页面、不执行页面里的任何东西。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs

# 允许的端口：默认端口和显式 80/443
_PORTS = {"80", "443"}

# 链接尾巴上可能粘着的标点（分享文本经常带这些）
_TRAILING = ".,!?)]}>\"'，。！？；：）】》」、"

# 一条链接的完整形态：
#   [协议://]  [m.|y.]music.163.com [:端口]  [/#/] /[m/]{song|playlist} [?查询串]
#
# 关键的前瞻/后顾断言：
#   * 开头的 (?<![A-Za-z0-9_./:@%?=&#-]) 保证域名前面不是域名/路径字符，
#     于是 evil.com/music.163.com、notmusic.163.com、user:pw@music.163.com
#     都匹配不上；
#   * 域名后面只能跟 :端口 或 /，因此 music.163.com.evil.net 匹配不上；
#   * 路径只认 song / playlist，专辑和 mv 不会被误当成歌曲。
_LINK_RE = re.compile(
    r"(?<![A-Za-z0-9_./:@%?=&#-])"
    r"(?:(?:https?:)?//)?"
    r"(?:m\.|y\.)?music\.163\.com"
    r"(?::(?P<port>\d{1,5}))?"
    r"(?:/(?:#/)?)?"
    r"(?:m/)?(?P<kind>song|playlist)"
    r"(?:\?(?P<query>[^\s<>\"'`()\[\]{},，。！？；：、（）【】《》「」]*))?",
    re.IGNORECASE,
)

# 网易云的编号是正整数，不允许前导零
_ID_RE = re.compile(r"[1-9][0-9]{0,19}")


@dataclass
class NcmLink:
    """一条识别出来的网易云链接。"""

    kind: str  # "song" | "playlist"
    ident: str  # 纯数字编号
    raw: str = ""  # 原始文本
    extra: dict = field(default_factory=dict)  # 附加信息（比如歌单名）

    @property
    def url(self) -> str:
        return f"https://music.163.com/{self.kind}?id={self.ident}"


def _parse_resource(match: re.Match) -> tuple[str, str] | None:
    """从正则命中里取出 (资源类型, 编号)，不合格返回 ``None``。"""
    port = match.group("port")
    if port is not None and port not in _PORTS:
        return None
    kind = (match.group("kind") or "").lower()
    if kind not in ("song", "playlist"):
        return None
    query = (match.group("query") or "").rstrip(_TRAILING)
    if not query:
        return None
    ids = parse_qs(query, keep_blank_values=True).get("id", [])
    if len(ids) != 1:
        return None
    ident = ids[0]
    if not _ID_RE.fullmatch(ident):
        return None
    return kind, ident


def extract_links(text: str) -> list[NcmLink]:
    """从消息文本里找出所有网易云链接，按首次出现顺序去重。"""
    found: list[NcmLink] = []
    seen: set[tuple[str, str]] = set()
    for match in _LINK_RE.finditer(text or ""):
        parsed = _parse_resource(match)
        if not parsed:
            continue
        kind, ident = parsed
        if (kind, ident) in seen:
            continue
        seen.add((kind, ident))
        found.append(NcmLink(kind=kind, ident=ident, raw=match.group(0)))
    return found


def extract_song_ids(text: str) -> list[str]:
    """只要单曲编号（歌单不算）。"""
    return [link.ident for link in extract_links(text) if link.kind == "song"]


def contains_link(text: str) -> bool:
    """文本里有没有可解析的网易云链接（用来给其他 handler 让路）。"""
    return bool(extract_links(text))
