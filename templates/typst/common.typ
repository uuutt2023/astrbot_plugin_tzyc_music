// 共享样式：调色板、字体、卡片底板、文本裁剪。
//
// 排版方案移植自 astrbot_plugin_blue_protocol（MIT，Copyright (c) 2026 uuutt）。
// 这里保留了那边的做法：尺寸单位统一是**CSS 像素**，模板用 style.scale 换算成 pt，
// 配置里填的就是「像素」，和浏览器一致。
//
//   style.scale = 72 / ppi，px(v) = v * scale * 1pt
//   144 PPI → 1px = 0.5pt，780px 宽的卡片导出后就是 780 像素宽
//
// Typst 两个容易踩的坑（都体现在下面的写法里）：
//   1. `context` 表达式把结果包成 content，不能直接参与数值比较；
//      要拿到测量值做判断，整个 if/else 必须写进 `context { }` 块里。
//   2. `block()` 没有 `align` 参数，块内居中要用 `align(center + horizon)[..]`。

#let palette(d) = {
  let c = d.at("colors", default: (:))
  (
    bg_top: rgb(c.at("bg_top", default: "F7F9FC")),
    bg_bottom: rgb(c.at("bg_bottom", default: "E8EDF4")),
    card: rgb(c.at("card", default: "FFFFFF")),
    border: rgb(c.at("border", default: "DEE3EB")),
    ink: rgb(c.at("ink", default: "1A1A1F")),
    muted: rgb(c.at("muted", default: "7A7F8A")),
    faint: rgb(c.at("faint", default: "A5AAB4")),
    accent: rgb(c.at("accent", default: "E12D3C")),
    white: rgb("FFFFFF"),
  )
}

// 字体名由宿主侧解析后写进 data.json（data.font），
// 避免模板里列一堆系统上并不存在的字族而刷出一屏 warning。
#let font_of(d) = d.at("font", default: "Noto Sans CJK SC")

// 按像素宽度截断文本，超出部分用省略号。
// Typst 没有内置的 text-overflow，只能自己量；注意测量值只有放进
// `context { }` 块里才能参与比较，所以整段逻辑都写在块内。
#let fit(body, max-width) = context {
  if measure(body).width <= max-width {
    body
  } else {
    let buf = ""
    for ch in body {
      let nxt = buf + ch
      if measure(nxt + "…").width > max-width { break }
      buf = nxt
    }
    buf + "…"
  }
}

// 标题左侧的红色竖条。height / width 都传「长度」，调用方用 px() 换算。
#let accent_bar(height, color, width: 4pt) = block(
  width: width,
  height: height,
  fill: color,
  radius: 2pt,
)

// 序号圆点
#let index_badge(n, color, size: 17pt, font-size: 12pt) = block(
  width: size,
  height: size,
  radius: size / 2,
  fill: color,
)[
  #align(center + horizon)[#text(size: font-size, weight: "bold", fill: rgb("FFFFFF"))[#str(n)]]
]

// 描边胶囊（音质 / VIP 标记）
// 尺寸参数都用「长度」，调用方按自己的比例用 px() 换算；
// radius 取高度一半就是胶囊。
#let pill(
  label,
  color,
  font-size: 9.5pt,
  pad-x: 8.5pt,
  pad-y: 4.5pt,
  stroke-width: 1pt,
) = context {
  let w = measure(text(size: font-size, weight: "bold")[#label]).width
  let h = font-size * 1.15 + pad-y * 2
  block(
    width: w + pad-x * 2,
    height: h,
    radius: h / 2,
    stroke: stroke-width + color,
  )[
    #align(center + horizon)[#text(size: font-size, weight: "bold", fill: color)[#label]]
  ]
}
