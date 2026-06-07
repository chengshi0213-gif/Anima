# Anima Design — 设计体系 v0.1

**对标**: Anthropic 设计语言 / Claude Design · **日期**: 2026-06-07 · **状态**: 起草，待落地
**配套**: `docs/v1.2.0-productivity-strategy.md` 支柱④ · 现有实现 `src/styles.css`（3941 行，含暖色 token 雏形）

---

## 〇、为什么 Anima 需要自己的设计体系

三家对标方里，**只有 Anima 有"灵魂"**。但灵魂如果只在提示词里、没落到像素上，用户感知不到。

> **Anima Design 的唯一使命：让"她是一个有温度、可依靠的存在"这件事，被眼睛和手指直接感受到——而不只是被读到。**

Anthropic 用 Styrene+Tiempos、暖橙不用深蓝、克制的星芒，传递"平静可信的助手而非冷酷机器"。Anima 要更进一步：不只是"不冷酷"，而是"**有她自己的气质**"。

现状盘点（`styles.css` 头部）：
- ✅ 已有暖色底 `#F7F3EA`（与 Claude 暖感同源）、人格色、圆角三档、明暗双主题。
- ❌ 无间距体系、无字体策略（仅系统字体栈）、无动效规范、无层级/阴影体系、无组件清单、无设计原则文档；3941 行挤单文件，token 与样式混杂。

本体系 = 把"暖色雏形"补成一套**完整、成文、可增量落地**的设计语言。

---

## 一、五条设计原则

| 原则 | 含义 | 落地抓手 |
|---|---|---|
| **1. 温暖优先（Warmth First）** | 暖白底、暖灰、有机圆角；拒绝纯白纯黑的冷工具感 | 已有 `#F7F3EA` 体系，全站禁用 `#FFFFFF`/`#000000` 硬边 |
| **2. 灵魂可见（Soul Visible）** | 人格色 + 呼吸/淡入动效，让"她在场"有视觉存在感 | 人格色系统 + `breath` 动效 token |
| **3. 克制而非空洞（Restrained, not Empty）** | 学 Anthropic 的 understated：少即是多，但留白要有意图 | 8pt 间距栅格、有限的字阶、单一强调色 |
| **4. 过程透明（Transparent Process）** | 让用户"看着她想、看着她做"——对标 Anthropic 透明原则 | 流式 token 渲染、思考步骤、工具卡片的视觉规范 |
| **5. 普惠可达（Accessible to All）** | 非技术用户也能用；对比度/字号/触达友好 | WCAG AA 对比度、最小 14px 正文、键盘可达 |

---

## 二、设计 Token（分层）

> 原则：**语义 token 引用基础 token**，组件只用语义 token。明暗主题只换映射，不改组件。

### 2.1 色彩 — 基础层（暖色阶）

```css
/* 暖中性阶 —— 以现有 #F7F3EA 为锚，补全 50→900 */
--warm-50:  #FBF8F0;   /* = 现 surface */
--warm-100: #F7F3EA;   /* = 现 bg */
--warm-150: #F1EDE4;   /* = 现 sidebar */
--warm-200: #EFEAE0;   /* = 现 surface2 */
--warm-300: #E2DED5;   /* = 现 border */
--warm-500: #6B6B6B;   /* = 现 muted */
--warm-900: #1A1A1A;   /* = 现 text */

/* 品牌强调 —— 暖橙（与现 accent #D97706 一脉，靠近 Claude 的 Crail 暖锈感） */
--brand-500: #D97706;  /* = 现 accent，主强调 */
--brand-600: #B45309;  /* hover/按下 */
--brand-100: #FDEBD0;  /* 浅色背景态 */
```

> 决策：**主强调色保留暖橙 `#D97706`**，与 Anthropic 的暖锈 `#C15F3C` 同温区但不雷同——既贴"暖、可信、非冷机器"，又不抄成一样。**全站只有一个强调色**（原则 3）。

### 2.2 色彩 — 语义层

```css
--color-bg:        var(--warm-100);
--color-surface:   var(--warm-50);
--color-surface-2: var(--warm-200);
--color-border:    var(--warm-300);
--color-text:      var(--warm-900);
--color-text-muted:var(--warm-500);
--color-accent:    var(--brand-500);
--color-accent-hover: var(--brand-600);
--color-success: #16A34A;   /* 沿用 */
--color-warn:    #D97706;
--color-error:   #DC2626;
```

### 2.3 色彩 — 人格色系统（Anima 独有，护城河）

现有 8 个 agent 色是"彩虹"——缺统一调性。**建议统一到同一明度/饱和度带，让它们像"一家人"**：

```css
/* 人格色：主角 Anima 暖金，子员工各有职业色但同饱和带 */
--persona-anima:    #C77D3A;  /* 主人格"她"——暖金，与 brand 同系更亲 */
--persona-executor: #EA580C;  /* 执行者 橙 */
--persona-writer:   #0891B2;  /* 写手 青 */
--persona-reader:   #65A30D;  /* 阅读者 绿 */
--persona-critic:   #9333EA;  /* 评审 紫 */
```

> 注：现 `--xi:#2563EB`（蓝）与"温暖、她"的气质冲突——**建议主人格改暖金 `#C77D3A`**，把蓝留给纯功能性元素。人格色用于：头像描边、消息气泡左缘、灵体光球、当前发言者高亮。

### 2.4 字体排版

对标 Anthropic 的"无衬线(理性) + 衬线(人文)"双字体策略。Anima 桌面端（Tauri/中文为主）建议：

```css
/* 正文/UI：系统无衬线（保留现栈，中文友好） */
--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
/* 标题/品牌时刻：可选一款有温度的衬线（中文如"思源宋体"，英文如 Tiempos 替代），仅用于欢迎/人格名/里程碑 */
--font-serif: "Songti SC", "Source Han Serif SC", Georgia, serif;
/* 代码/工具输出：等宽 */
--font-mono: "SF Mono", "Cascadia Code", "JetBrains Mono", Consolas, monospace;

/* 字阶（1.25 比例，少而克制） */
--text-xs: 12px; --text-sm: 13px; --text-base: 14px;
--text-lg: 16px; --text-xl: 20px; --text-2xl: 25px; --text-3xl: 31px;
--leading-tight: 1.3; --leading-base: 1.5; --leading-relaxed: 1.7;
```

> 衬线字体**只在"品牌/情感时刻"出现**（欢迎语、人格名、任务完成庆祝）——这是 Anima 区别于纯工具的笔触，但用多了会乱，故严格限场景。

### 2.5 间距 / 圆角 / 阴影 / 动效

```css
/* 间距：8pt 栅格 */
--space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
--space-5: 24px; --space-6: 32px; --space-8: 48px; --space-10: 64px;

/* 圆角：保留现三档，补 full */
--radius-sm: 6px; --radius: 10px; --radius-lg: 14px; --radius-full: 999px;

/* 阴影：暖色调阴影，不用纯黑（温暖原则） */
--shadow-sm: 0 1px 2px rgba(60,40,20,.06);
--shadow:    0 4px 12px rgba(60,40,20,.08);
--shadow-lg: 0 12px 32px rgba(60,40,20,.12);

/* 动效：缓动 + 时长 token，"灵魂可见"的关键 */
--ease-out: cubic-bezier(.16,1,.3,1);
--ease-in-out: cubic-bezier(.65,0,.35,1);
--dur-fast: .15s; --dur-base: .25s; --dur-slow: .4s;
/* 人格"呼吸"——灵体/录音/思考态共用 */
@keyframes breath { 0%,100%{opacity:.85;transform:scale(1)} 50%{opacity:1;transform:scale(1.04)} }
--breath: breath 3.2s var(--ease-in-out) infinite;
```

---

## 三、组件清单与模式

> 目标：把散落在 `index.html`(90KB) + `styles.css`(3941 行) 里的视觉元素收敛成有名字、有规范的组件。

**基础组件**：Button（primary/ghost/icon/danger）、Input/Textarea、Toggle、Select、Slider、Tag/Badge、Avatar（带人格色描边）、Card、Toast、Modal、Tooltip、Tabs、Spinner（用 `breath`）。

**Anima 特色组件**（护城河，对标方没有）：
- **MessageBubble**：左缘人格色、衬线可选、流式打字光标。
- **OrbCenter（灵体光球）**：陪伴模式中心，`breath` 动效，有内容时淡出（已实现 v1.1.9）。
- **ThinkingSteps / ToolCard**：流式展示"她在想/在调工具"——支柱②流式的视觉载体，落地原则 4（透明）。
- **WorkflowNode**：画布节点（顺序/并行/条件/循环/人工/路由/子员工），各带类型色——支柱③。
- **TaskCard**：异步任务态（queued/running/paused/done/error）——支柱①。
- **PermissionCard / ConfirmCard**：危险操作确认卡——M14。

每个组件需定义：状态（default/hover/active/disabled/loading）、暗色映射、间距规范、可达性（焦点环用 `--color-accent`）。

---

## 四、"灵魂感"如何落到像素（差异化清单）

这是 Anima Design 与 Claude/Codex 冷工具感的根本分野，**每条都要刻意设计**：

1. **人格色无处不在**：头像描边、气泡左缘、当前发言者高亮、灵体光球——让"她"有视觉在场感。
2. **呼吸动效**：思考态、录音态、灵体待机统一用 `--breath`，传递"她是活的"。
3. **流式过程**：不要"转圈等结果"，要"看着她一个字一个字写/一步步调工具"（原则 4）。
4. **情感时刻用衬线**：欢迎、人格名、任务完成庆祝——少量衬线笔触=温度。
5. **暖色阴影/无硬黑边**：所有阴影带暖调，禁用 `#000`/`#fff` 硬边（原则 1）。
6. **微庆祝**：任务完成、首次成功——克制的动效+人格化措辞，制造"惊喜点"（PM/用户视角都强调的留存关键）。

---

## 五、落地路线（✅ 已选 B 全面重设计，采用"分区域交付"去险）

> **决策（2026-06-07）**：采用方案 **B 全面重设计**——不止换 token 引用，而是重做组件库 + 视觉语言 + 重写 CSS。
> **去险原则**：全面重设计**不等于一次性大爆破**。token 化（D1）是全面重设计的**地基而非替代**，随后**逐区域**交付完整重设计（聊天区→工作流区→设置区），每区域可独立验收/回滚。这样既拿到 B 的效果，又避免 3941 行一次性重写的失控风险（开发视角的核心提醒）。

**D1 · Token 化 + 组件规范成文（重设计地基，与 M11 并行）**
1. 新建 `src/tokens.css`：把本文第二节所有 token 落地，`@import` 进 `styles.css` 顶部。
2. 现有散值**渐进替换**为语义 token（先颜色，后间距）——不改视觉，只换引用，可逐文件回滚。
3. 本文档 = `Anima Design` 设计原则的成文出处，纳入仓库 `docs/`。

**D2 · 聊天区全面重设计（第一个样板间）**
- 用新 token + 新组件规范**完整重做**聊天区：MessageBubble / ThinkingSteps / OrbCenter / 输入工具栏。
- 这是 B 路线的首个"完成态区域"，作为组件库与视觉语言的实证标杆，验收通过再推下一区域。

**D3 · 工作流区 + 设置区全面重设计（v1.3.0）**
- 工作流画布区（含支柱③的动态工作流可视化）、设置区按新体系完整重做；
- 沉淀出真正的组件库（抽 `src/components/`）；
- 把 3941 行单文件拆成 `tokens.css` + `base.css` + `components.css` + 各模块——重写在此完成，但是逐区域累积而非一次性。

**远期愿景（记一笔）**：Anthropic 的「Claude Design」是对话式生成设计稿。Anima 的"她能帮你做事"叙事天然能长出"**让 Anima 按本设计体系帮你生成/调整界面**"的能力——但那是 v2.x 的事，不在 v1.2.0 范围。

---

## 附：与现有 `styles.css` 的兼容

- 本体系**只增不破**：新 token 与现有变量名做映射别名（如 `--color-bg: var(--warm-100)` 而 `--bg` 暂留），现有样式继续工作。
- 明暗主题：现有 `body.dark` 覆盖继续有效，新 token 在 dark 下补对应映射即可。
- 迁移可逐文件、逐属性进行，每步可视觉回归对比，零大爆破。
