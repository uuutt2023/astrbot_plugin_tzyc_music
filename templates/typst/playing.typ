// 播放卡片：大 CD + 歌曲信息。
//
// 与 PIL 版（core/renderer.py::render_playing）同一套视觉：
//   左侧：带柔和投影的大 CD（盘面 PNG 由 Pillow 生成）
//   右侧：红色竖条 + 歌名、歌手、专辑 · 时长、音质/VIP 胶囊
//   右下：品牌角标
//
// 版式对齐 PIL 版像素坐标（980 × 520）。CD 的玻璃盘心由 Pillow 画成透明 PNG，
// Typst 只负责把它摆到版心里 —— 那是这个插件的视觉签名，手搓不划算。
#import "common.typ": *
#let d = json("data.json")
#let c = palette(d)
#let s = d.style
#let px(v) = v * s.scale * 1pt

#let W = s.width
#let H = s.height
#let pad = s.pad
#let disc_size = s.disc_size
#let disc_y = (H - disc_size) / 2
#let tx = pad + 12 + disc_size + 44
#let max_tw = W - tx - pad

#set page(width: px(W), height: px(H), margin: 0pt)
#set text(font: font_of(d), size: px(17), fill: c.ink)
#set page(fill: gradient.linear(c.bg_top, c.bg_bottom, angle: 90deg))

#block(width: px(W), height: px(H))[
  // ── 左侧大 CD（带柔和投影）──
  // 阴影和盘面一起画进了 PNG（Pillow 侧），所以这里只要摆一张图。
  #place(
    left + top,
    dx: px(pad + 12 - d.shadow_pad),
    dy: px(disc_y - d.shadow_pad),
    image(d.disc, width: px(disc_size + d.shadow_pad * 2), height: px(disc_size + d.shadow_pad * 2)),
  )

  // ── 右侧信息区 ──
  // 红色竖条 + 歌名
  #place(
    left + top,
    dx: px(tx),
    dy: px(pad + 20),
    accent_bar(px(44), c.accent),
  )
  #place(
    left + top,
    dx: px(tx + 24),
    dy: px(pad + 20),
    text(size: px(40), weight: "bold", fill: c.ink)[#fit(d.name, px(max_tw - 24))],
  )
  // 歌手
  #place(
    left + top,
    dx: px(tx),
    dy: px(pad + 116),
    text(size: px(26), fill: c.muted)[#fit(d.artists, px(max_tw))],
  )
  // 专辑 · 时长
  #place(
    left + top,
    dx: px(tx),
    dy: px(pad + 164),
    text(size: px(21), fill: c.faint)[#fit(d.meta, px(max_tw))],
  )
  // 音质 / VIP 胶囊
  #place(
    left + top,
    dx: px(tx),
    dy: px(pad + 214),
    pill(
      d.tag,
      c.at(d.at("tag_color", default: "accent"), default: c.accent),
      font-size: px(19),
      pad-x: px(17),
      pad-y: px(9),
      stroke-width: px(2),
    ),
  )

  // ── 品牌角标 ──
  #place(
    right + bottom,
    dx: px(-pad),
    dy: px(-pad + 4),
    text(size: px(20), weight: "bold", fill: c.faint)[#d.brand],
  )
]
