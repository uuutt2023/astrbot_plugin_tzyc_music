// 热评卡片：白卡 + 手绘引号 + 评论正文 + 用户信息。
//
// 与 PIL 版（core/renderer.py::render_comment）同一套视觉：
//   左上角两枚红色平行四边形引号（手绘，避开字体缺字形）
//   评论正文
//   分隔线 + 头像 + 昵称 + 「来自《歌名》的网易云热评」+ 点赞数
//
// 这里用**自动页高**（page(height: auto)）：评论正文由 Typst 自己折行，
// 卡片高度跟着内容走，不用在 Python 侧再估算一遍行数（估算和实际排版
// 总会差一点，估错了字就会被切掉）。
#import "common.typ": *
#let d = json("data.json")
#let c = palette(d)
#let s = d.style
#let px(v) = v * s.scale * 1pt

#let W = s.width
#let pad = s.pad
#let body_size = s.body_size
#let av_size = s.avatar_size
// 卡片外边距 17px，正文再往里 23px —— 和 PIL 版坐标一致
#let margin = pad / 2
#let inner = pad / 2 + 6

#set page(width: px(W), height: auto, margin: 0pt)
#set text(font: font_of(d), size: px(17), fill: c.ink)
#set page(fill: gradient.linear(c.bg_top, c.bg_bottom, angle: 90deg))

#block(width: px(W), inset: (left: px(margin), right: px(margin), top: px(margin), bottom: px(margin)))[
  #block(
    width: 100%,
    radius: px(22),
    fill: c.card,
    stroke: px(1) + c.border,
    inset: (left: px(inner), right: px(inner), top: px(inner), bottom: px(51)),
  )[
    // ── 引号：两枚红色平行四边形 ──
    #place(
      left + top,
      dx: 0pt,
      dy: 0pt,
      polygon(
        (0pt, px(34)),
        (px(15), 0pt),
        (px(31), 0pt),
        (px(16), px(34)),
        fill: c.accent,
      ),
    )
    #place(
      left + top,
      dx: px(30),
      dy: 0pt,
      polygon(
        (0pt, px(34)),
        (px(15), 0pt),
        (px(31), 0pt),
        (px(16), px(34)),
        fill: c.accent,
      ),
    )

    // ── 评论正文 ──
    #v(px(54))
    #text(size: px(body_size), fill: c.ink)[#d.content]
    #v(px(16))

    // ── 分隔线 ──
    #line(length: 100%, stroke: px(2) + c.border)
    #v(px(18))

    // ── 头像 + 昵称 + 来源 + 点赞 ──
    #grid(
      columns: (px(av_size), 1fr, auto),
      gutter: px(14),
      align: horizon,
      image(d.avatar, width: px(av_size), height: px(av_size)),
      block(width: 100%)[
        #text(size: px(21), fill: c.muted)[#fit(d.nickname, px(W - pad * 2 - av_size - 120))]
        #v(px(4))
        #text(size: px(18), fill: c.faint)[#fit(d.source, px(W - pad * 2 - av_size - 120))]
      ],
      align(right + horizon)[
        #if d.liked > 0 {
          text(size: px(21), fill: c.accent)[♥ #d.liked]
        }
      ],
    )
  ]
]
