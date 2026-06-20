/**
 * divination-viz.js — 命理三大招牌可视化（框架无关，纯 SVG 字符串）
 *
 * 由后端 interpret_chart().viz 的结构化数据驱动，颜色全走 CSS 变量（随墨夜翻色）。
 * 挂到 window.MingliViz。三件：
 *   wuxingRing(viz.wuxing)   五行生克环形图（外圈相生 / 内线相克 / 日主·喜用高亮）
 *   shishenBars(viz.shishen) 十神占比柱状图（十神固定语义色）
 *   dayunTimeline(viz.dayun) 大运评分时间轴（喜忌着色 + 诗题 + 当前运）
 */
(function () {
  "use strict";

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  // 五行 → CSS 变量名后缀
  const WX_KEY = { "木": "mu", "火": "huo", "土": "tu", "金": "jin", "水": "shui" };
  // 十神大类 → CSS 变量名后缀（比劫/食伤/财/官/印 = 蓝/绿/朱/褐/金）
  const SS_CAT = {
    "比肩": "bi", "劫财": "bi", "食神": "shi", "伤官": "shi",
    "正财": "cai", "偏财": "cai", "正官": "guan", "七杀": "guan",
    "正印": "yin", "偏印": "yin",
  };
  const polar = (cx, cy, r, deg) => {
    const a = (deg * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const n = (v) => Math.round(v * 100) / 100;

  // ── 1) 五行生克环形图 ────────────────────────────────────
  function wuxingRing(wx) {
    if (!wx || !wx.elements) return "";
    const els = wx.elements;                       // [木,火,土,金,水] 顺序
    const cx = 170, cy = 158, R = 96;
    const pos = els.map((_, i) => polar(cx, cy, R, -90 + i * 72));
    const radius = (p) => 22 + Math.min(18, (p.percent || 0) * 0.42);

    // 相生：相邻（外五边形边），箭头顺时针 i→i+1
    let sheng = "";
    for (let i = 0; i < 5; i++) {
      const a = pos[i], b = pos[(i + 1) % 5];
      sheng += `<line x1="${n(a[0])}" y1="${n(a[1])}" x2="${n(b[0])}" y2="${n(b[1])}"
        class="ml-ring__sheng" marker-end="url(#mlArrowSheng)"/>`;
    }
    // 相克：隔一（内五角星），i→i+2
    let ke = "";
    for (let i = 0; i < 5; i++) {
      const a = pos[i], b = pos[(i + 2) % 5];
      ke += `<line x1="${n(a[0])}" y1="${n(a[1])}" x2="${n(b[0])}" y2="${n(b[1])}"
        class="ml-ring__ke" marker-end="url(#mlArrowKe)"/>`;
    }
    // 节点
    let nodes = "";
    els.forEach((el, i) => {
      const [x, y] = pos[i];
      const r = radius(el);
      const key = WX_KEY[el.wuxing] || "shui";
      const out = polar(cx, cy, R + r + 14, -90 + i * 72);          // 十神对标签位
      const pairTop = (el.shishen_pair || "").slice(0, 2);
      const pairBot = (el.shishen_pair || "").slice(2, 4);
      nodes += `
        <g class="ml-ring__node${el.is_yong ? " is-yong" : ""}${el.is_day ? " is-day" : ""}" style="--wx:var(--ml-wx-${key})">
          ${el.is_yong ? `<circle cx="${n(x)}" cy="${n(y)}" r="${n(r + 5)}" class="ml-ring__halo"/>` : ""}
          <circle cx="${n(x)}" cy="${n(y)}" r="${n(r)}" class="ml-ring__disc"/>
          <text x="${n(x)}" y="${n(y - 2)}" class="ml-ring__wx">${esc(el.wuxing)}</text>
          <text x="${n(x)}" y="${n(y + 13)}" class="ml-ring__pct">${el.percent}%</text>
          ${el.is_day ? `<text x="${n(x)}" y="${n(y + r + 12)}" class="ml-ring__day">日主</text>` : ""}
          <text x="${n(out[0])}" y="${n(out[1] - 5)}" class="ml-ring__pair">${esc(pairTop)}</text>
          <text x="${n(out[0])}" y="${n(out[1] + 7)}" class="ml-ring__pair">${esc(pairBot)}</text>
        </g>`;
    });

    return `
    <svg class="ml-ring" viewBox="0 0 340 330" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="五行生克环形图">
      <defs>
        <marker id="mlArrowSheng" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" class="ml-ring__sheng-head"/></marker>
        <marker id="mlArrowKe" markerWidth="7" markerHeight="7" refX="5.5" refY="2.6" orient="auto">
          <path d="M0,0 L5,2.6 L0,5.2 Z" class="ml-ring__ke-head"/></marker>
      </defs>
      <g class="ml-ring__edges">${ke}${sheng}</g>
      ${nodes}
    </svg>`;
  }

  // ── 2) 十神占比柱状图 ────────────────────────────────────
  function shishenBars(list) {
    if (!list || !list.length) return "";
    const max = Math.max(...list.map((s) => s.percent), 1);
    const W = 360, padB = 38, padT = 14, H = 180;
    const bw = 22, gap = (W - list.length * bw) / (list.length + 1);
    const plotH = H - padB - padT;
    const bars = list.map((s, i) => {
      const x = gap + i * (bw + gap);
      const h = Math.max(2, (s.percent / max) * plotH);
      const y = padT + plotH - h;
      const cat = SS_CAT[s.name] || "bi";
      const dim = s.percent === 0 ? " is-zero" : "";
      return `<g class="ml-bar${dim}" style="--ss:var(--ml-ss-${cat})">
        <rect x="${n(x)}" y="${n(y)}" width="${bw}" height="${n(h)}" rx="4" class="ml-bar__rect"/>
        <text x="${n(x + bw / 2)}" y="${n(y - 4)}" class="ml-bar__pct">${s.percent}%</text>
        <text x="${n(x + bw / 2)}" y="${H - 20}" class="ml-bar__name">${esc(s.name.slice(0, 1))}</text>
        <text x="${n(x + bw / 2)}" y="${H - 8}" class="ml-bar__name">${esc(s.name.slice(1, 2))}</text>
      </g>`;
    }).join("");
    return `<svg class="ml-bars" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="十神占比">
      <line x1="0" y1="${H - padB + 2}" x2="${W}" y2="${H - padB + 2}" class="ml-bars__axis"/>${bars}</svg>`;
  }

  // ── 3) 大运评分时间轴 ────────────────────────────────────
  function dayunTimeline(list) {
    if (!list || !list.length) return "";
    const colW = 84, H = 250, padB = 52, padT = 56;
    const W = list.length * colW;
    const plotH = H - padB - padT;
    const toneCls = { "喜": "is-xi", "忌": "is-ji", "平": "is-ping" };
    const cols = list.map((d, i) => {
      const x = i * colW;
      const h = Math.max(8, (d.score / 100) * plotH);
      const y = padT + plotH - h;
      const cx = x + colW / 2;
      const tone = toneCls[d.xiyong] || "is-ping";
      const t = d.title || "";
      return `<g class="ml-dy ${tone}${d.current ? " is-now" : ""}">
        ${d.current ? `<rect x="${n(x + 6)}" y="${padT - 30}" width="${colW - 12}" height="${H - padB - padT + 50}" rx="8" class="ml-dy__cur"/>` : ""}
        <text x="${n(cx)}" y="${padT - 30}" class="ml-dy__title">${esc(t.slice(0, 2))}</text>
        <text x="${n(cx)}" y="${padT - 16}" class="ml-dy__title">${esc(t.slice(2, 4))}</text>
        <rect x="${n(cx - 16)}" y="${n(y)}" width="32" height="${n(h)}" rx="5" class="ml-dy__bar"/>
        <text x="${n(cx)}" y="${n(y - 5)}" class="ml-dy__score">${d.score}</text>
        <text x="${n(cx)}" y="${H - padB + 18}" class="ml-dy__age">${d.start_age}-${d.end_age}岁</text>
        <text x="${n(cx)}" y="${H - padB + 34}" class="ml-dy__gz">${esc(d.ganzhi)} ${esc(d.shishen)}</text>
        ${d.current ? `<text x="${n(cx)}" y="${H - 4}" class="ml-dy__nowtag">当前</text>` : ""}
      </g>`;
    }).join("");
    return `<div class="ml-dy-scroll"><svg class="ml-dy-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"
      xmlns="http://www.w3.org/2000/svg" role="img" aria-label="大运评分时间轴">${cols}</svg></div>`;
  }

  window.MingliViz = { wuxingRing, shishenBars, dayunTimeline };
})();
