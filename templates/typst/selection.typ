// 选歌列表：浅色磨砂底 + 白色行卡片 + 每行一张小 CD。
//
// 与 PIL 版（core/renderer.py::render_selection）同一套视觉：
//   顶部：红色竖条 + 「网易云点歌 · 关键词」
//   中部：每行一张白卡 —— 小 CD、序号圆点、歌名、歌手 · 专辑、时长
//   底部：回复序号点歌的提示
//
// 版式直接对齐 PIL 版的像素坐标（780 宽、每行 116 高），这样两张卡放一起
// 看不出差别。文本截断交给 common.typ 的 fit()。
//
// 注意：Typst 里 `{}` 内部是**代码模式**（不能再写 `#`），`[...]` 内部是标记模式。
#import "common.typ": *
#let d = json("data.json")
#let c = palette(d)
#let s = d.style
#let px(v) = v * s.scale * 1pt

#let W = s.width
#let pad = s.pad
#let row_h = s.row_h
#let header_h = s.header_h
#let footer_h = s.footer_h
#let H = header_h + row_h * d.rows.len() + footer_h + pad
#let disc = 92
#let text_x = pad + 12 + disc + 34 + 17 + 16

#set page(width: px(W), height: px(H), margin: 0pt)
#set text(font: font_of(d), size: px(17), fill: c.ink)
#set page(fill: gradient.linear(c.bg_top, c.bg_bottom, angle: 90deg))

#block(width: px(W), height: px(H))[
  // ── 顶部：红色竖条 + 标题 ──
  #place(
    left + top,
    dx: px(pad),
    dy: px(30),
    accent_bar(px(40), c.accent, width: px(8)),
  )
  #place(
    left + top,
    dx: px(pad + 22),
    dy: px(30),
    text(size: px(32), weight: "bold", fill: c.ink)[#fit(d.title, px(W - pad * 2 - 40))],
  )
  #place(
    left + top,
    dx: px(pad),
    dy: px(header_h - 8),
    line(length: px(W - pad * 2), stroke: px(2) + c.border),
  )

  // ── 每行一张白卡 ──
  //
  // 注意：`#for` 的循环体已经是**代码模式**，里面不能再写 `#`。
  // `place(...)` 的返回值是 content，循环里会被逐轮插进页面。
  #for i in range(d.rows.len()) {
    let row = d.rows.at(i)
    let y = header_h + i * row_h
    // 白色行卡片
    place(
      left + top,
      dx: px(pad),
      dy: px(y + 9),
      block(
        width: px(W - pad * 2),
        height: px(row_h - 18),
        radius: px(18),
        fill: c.card,
        stroke: px(1) + c.border,
      ),
    )
    // 小 CD（透明底 PNG，由 Pillow 生成，Typst 只负责摆位）
    place(
      left + top,
      dx: px(pad + 12),
      dy: px(y + 12),
      image(row.disc, width: px(disc), height: px(disc)),
    )
    // 序号圆点
    place(
      left + top,
      dx: px(pad + 12 + disc + 34),
      dy: px(y + row_h / 2 - 17),
      index_badge(row.n, c.accent, size: px(34), font-size: px(24)),
    )
    // 歌名 + 歌手/专辑
    place(
      left + top,
      dx: px(text_x),
      dy: px(y + 30),
      text(size: px(26), weight: "bold", fill: c.ink)[#fit(row.name, px(W - text_x - pad - 78))],
    )
    place(
      left + top,
      dx: px(text_x),
      dy: px(y + 68),
      text(size: px(20), fill: c.muted)[#fit(row.sub, px(W - text_x - pad - 78))],
    )
    // 时长（右对齐）
    place(
      right + top,
      dx: px(-pad - 18),
      dy: px(y + row_h / 2 - 13),
      text(size: px(19), fill: c.faint)[#row.duration],
    )
  }

  // ── 底部提示 ──
  #place(
    center + bottom,
    dy: px(-footer_h / 2 - 2),
    text(size: px(20), fill: c.faint)[#d.footer],
  )
]
