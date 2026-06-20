/**
 * divination-card.js — 命理「今日运势卡 + 命盘海报」渲染层（框架无关）
 *
 * 输入 = 后端 paipan() / daily_fortune() 的 JSON；输出 = 水墨命盘 DOM。
 * 纯渲染、无副作用、不依赖 Anima 其它模块，故预览页与 Tauri 应用共用同一份。
 * 盘面结构 fork 自 iztro 官方 react-iztro（4×4 宫格 + 中宫；四化色 禄/权/科/忌），
 * 皮肤见 divination-card.css。挂到 window.Mingli。
 */
(function () {
  "use strict";

  const MAIN_STARS = new Set(["紫微","天机","太阳","武曲","天同","廉贞","天府",
    "太阴","贪狼","巨门","天相","天梁","七杀","破军"]);
  // 紫微 12 宫在 4×4 盘面的固定格位（grid 行/列，1-indexed），中宫留给信息块
  const BRANCH_CELL = {
    "巳":[1,1],"午":[1,2],"未":[1,3],"申":[1,4],
    "辰":[2,1],                       "酉":[2,4],
    "卯":[3,1],                       "戌":[3,4],
    "寅":[4,1],"丑":[4,2],"子":[4,3],"亥":[4,4],
  };
  const ROMAN = ["0","Ⅰ","Ⅱ","Ⅲ","Ⅳ","Ⅴ","Ⅵ","Ⅶ","Ⅷ","Ⅸ","Ⅹ","Ⅺ","Ⅻ",
    "XIII","XIV","XV","XVI","XVII","XVIII","XIX","XX","XXI"];
  const RANK_GLYPH = { "侍从":"侍","骑士":"骑","王后":"后","国王":"王" };

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

  // 塔罗牌面图基址（公版 Rider-Waite）。预览页与 Tauri 应用都从根下 assets/ 取，可用 setAssetBase 覆盖。
  let ASSET = "assets/tarot/";
  function setAssetBase(base) { ASSET = base; }

  // 单条解读 section = {title, body?, items?}。body 与 items 可同时存在（body 先、items 后）。
  function _readItem(s) {
    let inner = "";
    if (s.body) inner += `<p class="mingli-read__body">${esc(s.body)}</p>`;
    if (s.items && s.items.length)
      inner += `<ul class="mingli-read__list">${s.items.map(i => `<li>${esc(i)}</li>`).join("")}</ul>`;
    if (!inner) inner = `<p class="mingli-read__body"></p>`;
    return `<div class="mingli-read__item"><div class="mingli-read__h">${esc(s.title)}</div>${inner}</div>`;
  }
  // 一组 section → 纯解读块（不含标题栏，详情页用）
  function readBlock(sections) {
    if (!sections || !sections.length) return "";
    return `<div class="mingli-read" data-reveal>${sections.map(_readItem).join("")}</div>`;
  }
  // 解读段落渲染（含标题栏，海报区用）
  function renderSections(title, sections, seal) {
    if (!sections || !sections.length) return "";
    return `
    <div class="mingli-rule"><span class="mingli-rule__t">${esc(title)}</span><span class="mingli-rule__l"></span>
      ${seal ? `<span class="mingli-rule__seal">${esc(seal)}</span>` : ""}</div>
    ${readBlock(sections)}`;
  }

  // ── 今日运势卡 ────────────────────────────────────────────
  function renderToday(f) {
    if (!f) return "";
    const a = f.almanac, t = f.tarot, p = f.personal || {};
    const seal = `is-${a.overall.tone}`;
    const chips = [];
    if (a.chong && a.chong.shengxiao)
      chips.push(`<span class="mingli-chip${p.chong_hit ? " is-warn" : ""}">冲 <b>${esc(a.chong.shengxiao)}</b> · 煞${esc(a.chong.sha)}</span>`);
    if (a.tian_shen && a.tian_shen.name)
      chips.push(`<span class="mingli-chip">${esc(a.tian_shen.name)}·${esc(a.tian_shen.type)}（${esc(a.tian_shen.luck)}）</span>`);
    if (a.zhixing) chips.push(`<span class="mingli-chip">${esc(a.zhixing)}日</span>`);
    if (a.xiu) chips.push(`<span class="mingli-chip">${esc(a.xiu)}宿</span>`);
    if (a.jieqi && a.jieqi.next) chips.push(`<span class="mingli-chip">近 ${esc(a.jieqi.next)}</span>`);

    const tarotGlyph = t.arcana === "major" ? (ROMAN[t.id] || "✦")
      : (RANK_GLYPH[t.rank] || esc(t.rank || ""));
    const tarotNum = t.arcana === "major" ? "大阿尔卡那" : esc(t.suit || "");
    const tags = (t.keywords || []).map(k => `<span class="mingli-tag">${esc(k)}</span>`).join("");
    const tips = (p.tips || []).map(s => `<div class="mingli-tips__li">· ${esc(s)}</div>`).join("");

    // 今日运程：四维分项（focus=今日主场）+ 喜用幸运物
    const stars = (n) => `<span class="on">${"★".repeat(n)}</span><span class="off">${"★".repeat(5 - n)}</span>`;
    const aspectRows = (f.aspects || []).map(x => `
      <div class="mingli-aspect${x.focus ? " is-focus" : ""}">
        <div class="mingli-aspect__top">
          <span class="mingli-aspect__name">${esc(x.domain)}${x.focus ? '<span class="mingli-aspect__focus">今日主场</span>' : ""}</span>
          <span class="mingli-aspect__stars">${stars(x.stars)}</span>
        </div>
        <div class="mingli-aspect__read">${esc(x.text)}</div>
        <div class="mingli-aspect__adv">▸ ${esc(x.advice)}</div>
      </div>`).join("");
    const lk = f.lucky || {};
    const luckyHtml = lk.color ? `
      <div class="mingli-lucky">
        <span class="mingli-lucky__i">幸运色 <b>${esc(lk.color)}</b></span>
        <span class="mingli-lucky__i">幸运数 <b>${esc(lk.numbers)}</b></span>
        <span class="mingli-lucky__i">吉位 <b>${esc(lk.direction)}</b></span>
      </div>` : "";
    const luckHd = lk.wuxing
      ? `<span class="mingli-rule__seal">喜用·${esc(lk.wuxing)}</span>` : "";
    const todayRun = (aspectRows || luckyHtml) ? `
      <div class="mingli-rule"><span class="mingli-rule__t">今日运程</span><span class="mingli-rule__l"></span>${luckHd}</div>
      <div data-reveal>
        <div class="mingli-aspects">${aspectRows}</div>
        ${luckyHtml}
        <div class="mingli-note">分项是「你的日主 × 今日天干」的能量倾向（非流日吉凶预测）；幸运物取你的喜用五行。</div>
      </div>` : "";

    return `
    <div class="mingli-today" data-reveal>
      <div class="mingli-today__hd">
        <div class="mingli-today__date">
          <div><span class="d-greg">${esc(a.solar)}</span><span class="d-week">${esc(a.weekday)}</span></div>
          <div class="d-lunar">${esc(a.lunar_date)}</div>
          <div class="d-gz">${esc(a.ganzhi.year)}年 ${esc(a.ganzhi.month)}月 ${esc(a.ganzhi.day)}日</div>
        </div>
        <div class="mingli-seal ${seal}"><div><b>${esc(a.overall.label)}</b><span>今日</span></div></div>
      </div>

      <div class="mingli-yiji" data-reveal>
        <div class="mingli-yiji__col mingli-yiji--yi">
          <div class="mingli-yiji__h"><span class="mingli-yiji__badge">宜</span>宜</div>
          <div class="mingli-yiji__items">${(a.yi||[]).map(x=>esc(x)).join("&nbsp;·&nbsp;")||"—"}</div>
        </div>
        <div class="mingli-yiji__col mingli-yiji--ji">
          <div class="mingli-yiji__h"><span class="mingli-yiji__badge">忌</span>忌</div>
          <div class="mingli-yiji__items">${(a.ji||[]).map(x=>esc(x)).join("&nbsp;·&nbsp;")||"—"}</div>
        </div>
      </div>

      <div class="mingli-chips" data-reveal>${chips.join("")}</div>

      ${todayRun}

      <div class="mingli-rule"><span class="mingli-rule__t">今日塔罗</span><span class="mingli-rule__l"></span>
        <span class="mingli-rule__seal">每日一抽</span></div>
      <div class="mingli-tarot" data-reveal>
        <div class="mingli-tcard">
          <div class="mingli-tcard__frame">
            <img class="mingli-tcard__img${t.orientation==="reversed"?" is-rev":""}" loading="lazy"
                 src="${ASSET}${t.id}.jpg" alt="${esc(t.name_zh)}"
                 onerror="this.classList.add('img-fail')">
            <div class="mingli-tcard__glyph">${tarotGlyph}<small>${tarotNum}</small></div>
            ${t.orientation==="reversed"?'<span class="mingli-tcard__rev">逆</span>':""}
          </div>
          <div class="mingli-tcard__cap">${esc(t.name_zh)}</div>
          <div class="mingli-tcard__en">${esc(t.name_en)}</div>
        </div>
        <div class="mingli-tarot__body">
          <div class="mingli-tarot__title">${esc(t.name_zh)}<span class="ori">${esc(t.orientation_zh)}</span></div>
          <div class="mingli-tags">${tags}</div>
          <div class="mingli-tarot__meaning">${esc(t.meaning)}</div>
        </div>
      </div>

      ${(f.greeting || tips) ? `
      <div class="mingli-tips" data-reveal>
        ${f.greeting?`<div class="mingli-tips__greet">${esc(f.greeting)}</div>`:""}
        ${tips}
      </div>` : ""}
    </div>`;
  }

  // ── 八字四柱 ──────────────────────────────────────────────
  function renderBazi(b) {
    if (!b) return "";
    const P = b.pillars, cols = ["year","month","day","time"], label = ["年柱","月柱","日柱","时柱"];
    const cells = cols.map((c,i)=>{
      const x = P[c];
      return `<div class="mingli-pillar">
        <div class="mingli-pillar__label">${label[i]}</div>
        <div class="mingli-pillar__gz"><span class="gan">${esc(x.gan)}</span><span class="zhi">${esc(x.zhi)}</span></div>
        <div class="mingli-pillar__sub">
          <div>${(x.hide_gan||[]).map(esc).join("")||"—"}</div>
          <div>${esc(x.shishen_gan||"")}</div>
          <div class="nayin">${esc(x.nayin||"")}</div>
        </div>
      </div>`;
    }).join("");
    const dy = (b.dayun||[]).slice(0,8).map(d=>`<span>${esc(d.start_age)}岁 <b>${esc(d.ganzhi)}</b></span>`).join("");
    const note = b.time_unknown ? `<span class="mingli-note">（时辰未知，时柱按午时近似）</span>` : "";
    return `
    <div class="mingli-rule"><span class="mingli-rule__t">八字四柱</span><span class="mingli-rule__l"></span></div>
    <div data-reveal>
      <div class="mingli-bazi-meta">${esc(b.solar)}　${esc(b.lunar)}　日主 <b>${esc(b.day_master)}（${esc(b.day_master_wuxing)}）</b>　命宫 <b>${esc(b.ming_gong)}</b>　身宫 <b>${esc(b.shen_gong)}</b> ${note}</div>
      <div class="mingli-pillars">${cells}</div>
      <div class="mingli-dayun">大运 · ${dy}</div>
    </div>`;
  }

  // ── 紫微十二宫盘 ──────────────────────────────────────────
  function renderZiwei(z) {
    if (!z) return "";
    const dxByBranch = {};
    (z.daxian||[]).forEach(d => { dxByBranch[d.branch] = d.age_range; });
    const cells = (z.palaces||[]).map(pal => {
      const [r,c] = BRANCH_CELL[pal.branch] || [1,1];
      const stars = (pal.stars||[]).map(s => {
        const cls = MAIN_STARS.has(s.name) ? "major" : "minor";
        const sh = (s.sihua||[]).map(t => { const ch = t.replace("化",""); return `<span class="mingli-sihua s-${ch}">${ch}</span>`; }).join("");
        return `<div class="mingli-star ${cls}">${esc(s.name)}${sh}</div>`;
      }).join("") || `<div class="mingli-star minor" style="color:var(--ml-ink-3)">空宫</div>`;
      const dx = dxByBranch[pal.branch];
      const dxTxt = dx ? `${dx[0]}–${dx[1]}` : "";
      const isMing = pal.name === "命宫";
      return `<div class="mingli-pal${isMing?" is-ming":""}" style="grid-row:${r};grid-column:${c}">
        <div class="mingli-pal__stars">${stars}</div>
        <div class="mingli-pal__ft">
          <span class="mingli-pal__name">${esc(pal.name)}${pal.is_shen_gong?'<span class="shen">·身</span>':""}</span>
          <span class="mingli-pal__gz">${esc(pal.ganzhi)}</span>
        </div>
        ${dxTxt?`<div class="mingli-pal__dx" style="font-size:10px;font-family:var(--ml-sans);color:var(--ml-ink-3)">大限 ${dxTxt}</div>`:""}
      </div>`;
    }).join("");

    const sh = z.sihua || {};
    const shTxt = Object.keys(sh).map(k => {
      const ch = k.replace("化","");
      return `<span><span class="mingli-sihua s-${ch}">${ch}</span> ${esc(sh[k])}</span>`;
    }).join("");
    const note = z.time_unknown ? `<div class="mingli-note">（时辰未知，命宫与十二宫仅供参考）</div>` : "";
    const center = `<div class="mingli-pal mingli-center" style="grid-row:2/4;grid-column:2/4">
      <div class="mingli-center__ju">${esc(z.wuxing_ju)}</div>
      <div class="mingli-center__row">${esc(z.year_ganzhi)}年生</div>
      <div class="mingli-center__row">命宫 <b>${esc(z.ming_gong.ganzhi)}</b>　身宫 <b>${esc(z.shen_gong.branch)}</b></div>
      <div class="mingli-center__row">紫微在<b>${esc(z.ziwei_branch)}</b>　天府在<b>${esc(z.tianfu_branch)}</b></div>
      <div class="mingli-center__sihua">${shTxt}</div>
    </div>`;

    return `
    <div class="mingli-rule"><span class="mingli-rule__t">紫微斗数</span><span class="mingli-rule__l"></span>
      <span class="mingli-rule__seal">十二宫</span></div>
    <div data-reveal><div class="mingli-ziwei">${cells}${center}</div>${note}</div>`;
  }

  function renderPoster(chart) {
    if (!chart) return "";
    const interp = chart.interpretation || {};
    return renderBazi(chart.bazi)
      + renderSections("八字浅释", interp.bazi, "滴天髓·子平")
      + renderZiwei(chart.ziwei)
      + renderSections("紫微浅释", interp.ziwei, "中州派");
  }

  // 把一段命盘 HTML 装进 rootEl 并触发克制的一次性入场动效（reduce-motion / 无 gsap 均有兜底）
  function _mountHtml(rootEl, innerHtml, opts) {
    opts = opts || {};
    rootEl.classList.add("mingli");
    rootEl.classList.toggle("is-night", !!opts.night);
    rootEl.classList.remove("revealed");
    rootEl.innerHTML = `<div class="mingli-sheet">${innerHtml}</div>`;
    const items = rootEl.querySelectorAll("[data-reveal]");
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { rootEl.classList.add("revealed"); return rootEl; }
    if (window.gsap) {
      window.gsap.fromTo(items, { opacity:0, y:12 },
        { opacity:1, y:0, duration:.5, ease:"power3.out", stagger:.07, clearProps:"all" });
      rootEl.classList.add("revealed");
    } else {
      requestAnimationFrame(() => requestAnimationFrame(() => rootEl.classList.add("revealed")));
    }
    return rootEl;
  }

  /** 今日运势卡 + 命盘海报 全套。data = { chart, fortune }。opts.night=墨夜。 */
  function mount(rootEl, data, opts) {
    data = data || {};
    return _mountHtml(rootEl, renderToday(data.fortune) + renderPoster(data.chart), opts);
  }
  /** 只挂今日运势卡（日常高频用）。 */
  function mountToday(rootEl, fortune, opts) { return _mountHtml(rootEl, renderToday(fortune), opts); }
  /** 只挂命盘海报（八字 + 紫微）。 */
  function mountPoster(rootEl, chart, opts) { return _mountHtml(rootEl, renderPoster(chart), opts); }

  // ══════════════════════════════════════════════════════════
  //  导航卡面（master-detail）：总览=摘要卡网格，点卡片→详情页
  // ══════════════════════════════════════════════════════════
  const GAN_YY = { "甲": "阳木", "乙": "阴木", "丙": "阳火", "丁": "阴火", "戊": "阳土",
    "己": "阴土", "庚": "阳金", "辛": "阴金", "壬": "阳水", "癸": "阴水" };
  const WX_LUCKY = {
    "木": { color: "青绿色", direction: "东方", numbers: "3、8" },
    "火": { color: "红 · 橙色", direction: "南方", numbers: "2、7" },
    "土": { color: "黄 · 棕色", direction: "西南 · 中宫", numbers: "5、0" },
    "金": { color: "白 · 金色", direction: "西方", numbers: "4、9" },
    "水": { color: "黑 · 蓝色", direction: "北方", numbers: "1、6" },
  };
  const _viz = () => window.MingliViz || {};
  const _firstClause = (t, max) => {
    if (!t) return "";
    let s = String(t).trim();
    const m = s.match(/^[^。！？；\n]+/);
    s = m ? m[0] : s;
    const lim = max || 38;
    return s.length > lim ? s.slice(0, lim) + "…" : s;
  };
  const _bracket = (t) => { const m = String(t || "").match(/「([^」]+)」/); return m ? m[1] : ""; };
  const _find = (arr, kw) => (arr || []).find(s => s.title && s.title.indexOf(kw) >= 0) || null;
  const _findAll = (arr, kws) => kws.map(k => _find(arr, k)).filter(Boolean);
  const _mingStars = (z) => {
    const p = ((z || {}).palaces || []).find(x => x.name === "命宫");
    return p ? (p.stars || []).filter(s => MAIN_STARS.has(s.name)).map(s => s.name).join("、") : "";
  };
  const _curDayun = (viz) => ((viz.dayun || []).find(d => d.current) || null);

  function _ctx(data) {
    const chart = (data || {}).chart || {};
    const interp = chart.interpretation || {};
    return {
      chart, fortune: (data || {}).fortune || null,
      bz: interp.bazi || [], zw: interp.ziwei || [], viz: interp.viz || {},
      bazi: chart.bazi || {}, ziwei: chart.ziwei || {},
    };
  }

  // 喜用幸运物块（五行详情用）
  function _yongHtml(c) {
    const yong = (c.viz.wuxing || {}).yongshen || "";
    let lk = (c.fortune && c.fortune.lucky && c.fortune.lucky.wuxing === yong)
      ? c.fortune.lucky : (WX_LUCKY[yong] ? Object.assign({ wuxing: yong }, WX_LUCKY[yong]) : null);
    if (!lk) return "";
    return `<div class="mlx-yong">
      <div class="mlx-yong__h">喜用 ${esc(yong)} · 本命幸运物</div>
      <div class="mlx-yong__row">
        <span class="mlx-yong__i">幸运色 <b>${esc(lk.color)}</b></span>
        <span class="mlx-yong__i">吉位 <b>${esc(lk.direction)}</b></span>
        <span class="mlx-yong__i">幸运数 <b>${esc(lk.numbers)}</b></span>
      </div></div>`;
  }

  // 卡片清单：每张 = {key, group, seal, title, summary(c), badge(c)?, detail(c), show(c)?}
  const CARD_SPECS = [
    { key: "today", group: "today", seal: "日", title: "今日运势", wide: true,
      show: (c) => !!c.fortune,
      summary: (c) => {
        const f = c.fortune || {};
        const parts = [];
        if (f.focus_domain) parts.push("今日主场 · " + f.focus_domain);
        if (f.greeting) parts.push(f.greeting);
        return parts.join("｜");
      },
      badge: (c) => {
        const o = ((c.fortune || {}).almanac || {}).overall || {};
        const tone = { good: "good", neutral: "neutral", bad: "warn" }[o.tone] || "neutral";
        return o.label ? { text: o.label, tone } : null;
      },
      detail: (c) => renderToday(c.fortune) },

    // —— 八字 ——
    { key: "rizhu", group: "bazi", seal: "性", title: "日主性格",
      summary: (c) => _bracket((_find(c.bz, "日主") || {}).body) || "看你的内在底色",
      detail: (c) => readBlock(_findAll(c.bz, ["日主"])) },
    { key: "gelu", group: "bazi", seal: "格", title: "格局旺衰",
      summary: (c) => {
        const g = (c.viz.geju || {}).name || "", w = (c.viz.wangshuai || {}).level || "";
        return [g, w ? "日主" + w : ""].filter(Boolean).join(" · ") || "命格定性";
      },
      detail: (c) => readBlock(_findAll(c.bz, ["格局", "旺衰"])) },
    { key: "wuxing", group: "bazi", seal: "行", title: "五行能量",
      summary: (c) => {
        const w = c.viz.wuxing || {};
        const miss = (w.missing || []).length ? "缺" + (w.missing || []).join("") : "五行俱全";
        return `最旺 ${w.strongest || "—"} · ${miss}`;
      },
      detail: (c) => {
        const ring = _viz().wuxingRing ? _viz().wuxingRing(c.viz.wuxing) : "";
        return `<div class="mlx-hero" data-reveal>${ring}
          <div class="mlx-legend"><i>外圈相生</i><i>内线相克</i><i style="color:var(--ml-cinnabar)">⊙ 喜用</i></div>
          ${_yongHtml(c)}</div>` + readBlock(_findAll(c.bz, ["五行"]));
      } },
    { key: "dayun", group: "bazi", seal: "运", title: "大运走势",
      summary: (c) => {
        const d = _curDayun(c.viz);
        return d ? `当前 ${d.ganzhi} ${d.shishen}运 · ${d.score}分` : "十年一运的节奏";
      },
      badge: (c) => {
        const d = _curDayun(c.viz);
        if (!d) return null;
        const tone = { "喜": "good", "忌": "warn", "平": "neutral" }[d.xiyong] || "neutral";
        return { text: d.score + "", tone };
      },
      detail: (c) => {
        const tl = _viz().dayunTimeline ? _viz().dayunTimeline(c.viz.dayun) : "";
        return `<div class="mlx-hero" data-reveal>${tl}
          <div class="mlx-hero__cap">柱高 = 运势评分（喜用之运分高）· 朱=喜 / 墨=忌 / 茶=平 · 圈出你当前所在</div></div>`
          + readBlock(_findAll(c.bz, ["大运"]));
      } },
    { key: "shishen", group: "bazi", seal: "神", title: "十神格局",
      summary: (c) => {
        const s = (c.viz.shishen || []).slice().sort((a, b) => b.percent - a.percent)[0];
        return s ? `最旺 ${s.name} ${s.percent}%` : "十神能量分布";
      },
      detail: (c) => {
        const bars = _viz().shishenBars ? _viz().shishenBars(c.viz.shishen) : "";
        return `<div class="mlx-hero" data-reveal>${bars}
          <div class="mlx-hero__cap">天干（除日主）+ 藏干加权统计的十神占比</div></div>`
          + readBlock(_findAll(c.bz, ["月令"]));
      } },
    { key: "tiaohou", group: "bazi", seal: "候", title: "调候用神",
      summary: (c) => _firstClause((_find(c.bz, "调候") || {}).body) || "寒暖燥湿的平衡",
      detail: (c) => readBlock(_findAll(c.bz, ["调候"])) },
    { key: "sizhu", group: "bazi", seal: "柱", title: "四柱八字",
      summary: (c) => {
        const P = c.bazi.pillars || {};
        return ["year", "month", "day", "time"].map(k => (P[k] || {}).ganzhi || "").filter(Boolean).join(" ");
      },
      detail: (c) => renderBazi(c.bazi) + readBlock(_findAll(c.bz, ["四柱"])) },
    { key: "ganzhi", group: "bazi", seal: "合", title: "刑冲合会",
      show: (c) => !!_find(c.bz, "干支"),
      summary: (c) => {
        const s = _find(c.bz, "干支");
        return s && s.items ? `${s.items.length} 组刑冲合会` : "地支之间的牵动";
      },
      detail: (c) => readBlock(_findAll(c.bz, ["干支"])) },
    { key: "changsheng", group: "bazi", seal: "生", title: "十二长生",
      show: (c) => !!_find(c.bz, "长生"),
      summary: (c) => {
        const s = _find(c.bz, "长生");
        const day = s && s.items ? (s.items.find(x => x.indexOf("日支") >= 0) || "") : "";
        const st = _bracket(day);
        return st ? `日支居「${st}」` : "命主的生命周期";
      },
      detail: (c) => readBlock(_findAll(c.bz, ["长生"])) },

    // —— 紫微 ——
    { key: "zwpan", group: "ziwei", seal: "盘", title: "紫微命盘",
      show: (c) => !!(c.ziwei && c.ziwei.palaces),
      summary: (c) => {
        const ms = _mingStars(c.ziwei);
        const ju = c.ziwei.wuxing_ju || "";
        return [ms ? ms + " 坐命" : "", ju].filter(Boolean).join(" · ") || "十二宫全盘";
      },
      detail: (c) => renderZiwei(c.ziwei) },
    { key: "mingstar", group: "ziwei", seal: "命", title: "命宫主星",
      show: (c) => !!_find(c.zw, "命宫主星"),
      summary: (c) => {
        const m = String((_find(c.zw, "命宫主星") || {}).body || "").match(/【(.+?)】([^。\n]+)/);
        return m ? `${m[1]} · ${m[2]}`.slice(0, 30) : "你的本命主星";
      },
      detail: (c) => readBlock(_findAll(c.zw, ["命宫主星", "辅煞"])) },
    { key: "sihua", group: "ziwei", seal: "化", title: "生年四化",
      show: (c) => !!_find(c.zw, "四化"),
      summary: (c) => {
        const s = _find(c.zw, "四化");
        const ji = s && s.items ? (s.items.find(x => x.indexOf("化忌") >= 0) || "") : "";
        return _firstClause(ji) || "禄权科忌落宫";
      },
      detail: (c) => readBlock(_findAll(c.zw, ["四化"])) },
    { key: "gege", group: "ziwei", seal: "局", title: "参考格局",
      show: (c) => !!_find(c.zw, "参考格局"),
      summary: (c) => {
        const s = _find(c.zw, "参考格局");
        return s && s.items ? `${s.items.length} 个参考格局` : "命盘格局参看";
      },
      detail: (c) => readBlock(_findAll(c.zw, ["参考格局"])) },
    { key: "axis-career", group: "ziwei", seal: "业", title: "事业主轴",
      show: (c) => !!_find(c.zw, "事业主轴"),
      summary: () => "命 · 财 · 官 · 迁 四宫联看",
      detail: (c) => readBlock(_findAll(c.zw, ["事业主轴"])) },
    { key: "axis-people", group: "ziwei", seal: "缘", title: "人际关系",
      show: (c) => !!_find(c.zw, "人际"),
      summary: () => "夫妻 · 子女 · 交友",
      detail: (c) => readBlock(_findAll(c.zw, ["人际"])) },
    { key: "axis-life", group: "ziwei", seal: "活", title: "生活底色",
      show: (c) => !!_find(c.zw, "生活底色"),
      summary: () => "父母 · 疾厄 · 福德 · 田宅",
      detail: (c) => readBlock(_findAll(c.zw, ["生活底色"])) },
    { key: "shengong", group: "ziwei", seal: "身", title: "身宫着力",
      show: (c) => !!_find(c.zw, "身宫"),
      summary: (c) => {
        const b = (_find(c.zw, "身宫") || {}).body || "";
        const p = _bracket(b);
        return p ? `身宫落「${p}」` : "后天着力的方向";
      },
      detail: (c) => readBlock(_findAll(c.zw, ["身宫"])) },
  ];
  const _spec = (key) => CARD_SPECS.find(s => s.key === key);

  function _cardHtml(spec, c) {
    const sum = spec.summary ? spec.summary(c) : "";
    const b = spec.badge ? spec.badge(c) : null;
    const badge = b ? (b.tag
      ? `<span class="mlx-tag">${esc(b.tag)}</span>`
      : `<span class="mlx-score mlx-score--${b.tone || "neutral"}">${esc(b.text)}</span>`) : "";
    return `<button type="button" class="mlx-card${spec.wide ? " is-wide" : ""}" data-nav="card:${spec.key}">
      <span class="mlx-card__seal">${esc(spec.seal)}</span>
      <span class="mlx-card__body">
        <span class="mlx-card__top"><span class="mlx-card__title">${esc(spec.title)}</span>${badge}</span>
        ${sum ? `<span class="mlx-card__sum">${esc(sum)}</span>` : ""}
      </span>
      <span class="mlx-card__chev">›</span>
    </button>`;
  }
  const _sec = (t) => `<div class="mlx-sec"><span class="mlx-sec__t">${esc(t)}</span><span class="mlx-sec__l"></span></div>`;

  function renderOverview(data) {
    const c = _ctx(data);
    const dayGz = ((c.bazi.pillars || {}).day || {}).ganzhi || "";
    const dm = c.bazi.day_master || "";
    const idSub = [dm ? `日主 <b>${esc(dm)}</b>` : "", GAN_YY[dm] || "",
      (c.viz.geju || {}).name || "", (c.viz.wangshuai || {}).level ? "身" + c.viz.wangshuai.level : ""]
      .filter(Boolean).join(" · ");
    const grid = (group) => {
      const html = CARD_SPECS.filter(s => s.group === group && (!s.show || s.show(c)))
        .map(s => _cardHtml(s, c)).join("");
      return html ? `<div class="mlx-grid" data-reveal>${html}</div>` : "";
    };
    const todaySpec = _spec("today");
    const today = (todaySpec && todaySpec.show(c)) ? `<div class="mlx-grid" data-reveal>${_cardHtml(todaySpec, c)}</div>` : "";
    return `<div class="mlx-id" data-reveal>
        <div class="mlx-id__title">${esc(dayGz)}日出生的自己</div>
        ${idSub ? `<div class="mlx-id__sub">${idSub}</div>` : ""}
      </div>`
      + today
      + _sec("八字 · 生辰") + grid("bazi")
      + (grid("ziwei") ? _sec("紫微 · 斗数") + grid("ziwei") : "");
  }

  function renderDetail(data, key) {
    const c = _ctx(data);
    const spec = _spec(key);
    if (!spec) return renderOverview(data);
    return `<div class="mlx-back">
        <button type="button" class="mlx-back__btn" data-nav="back">‹ 返回</button>
        <span class="mlx-back__title">${esc(spec.title)}</span>
      </div>` + spec.detail(c);
  }

  function _renderSurface(state) {
    const route = state.stack[state.stack.length - 1];
    const html = route.view === "overview"
      ? renderOverview(state.data) : renderDetail(state.data, route.key);
    _mountHtml(state.rootEl, html, state.opts);
    try { state.rootEl.scrollIntoView({ block: "start", behavior: "auto" }); } catch (e) {}
    state.rootEl.querySelectorAll("[data-nav]").forEach(el => {
      el.addEventListener("click", () => {
        const nav = el.getAttribute("data-nav");
        if (nav === "back") {
          if (state.stack.length > 1) { state.stack.pop(); _renderSurface(state); }
        } else if (nav.indexOf("card:") === 0) {
          state.stack.push({ view: "detail", key: nav.slice(5) });
          _renderSurface(state);
        }
      });
    });
  }

  /** 导航卡面：总览⇄详情。data = { chart, fortune }。opts.night=墨夜。 */
  function mountSurface(rootEl, data, opts) {
    const state = { rootEl, data: data || {}, opts: opts || {}, stack: [{ view: "overview" }] };
    rootEl.__mlState = state;
    _renderSurface(state);
    return rootEl;
  }
  /** 切换墨夜/重渲染但保留导航栈位置（预览/主题切换用）。 */
  function refreshSurface(rootEl, opts) {
    const state = rootEl.__mlState;
    if (!state) return;
    if (opts) state.opts = Object.assign({}, state.opts, opts);
    _renderSurface(state);
  }

  window.Mingli = {
    mount, mountToday, mountPoster, mountSurface, refreshSurface,
    renderToday, renderPoster, renderBazi, renderZiwei, renderOverview, renderDetail, setAssetBase,
  };
})();
