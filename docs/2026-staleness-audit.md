# 2026 过时排查：对标 Codex/Claude Code 还成立吗？

> 背景：v1.2.x 的"对标 Codex/Claude Code"规划由 2025 知识截止的会话写于 2026-06-10，
> 很可能对标的是 **2025 年初的形态**。本文档用 2026-06 一手信源排查哪些过时、哪些依然成立。
> 排查日期：2026-06-13。

---

## 一、2026 年中的真实形态（一手信源）

### Codex（OpenAI）
- 模型已是 **GPT-5.3-Codex**。
- **战略转向**：从"编程助手"→"商业专业人士的日常操作环境"（*Codex for almost everything*）。
- 新增 **6 个角色插件**（数据分析/创意/销售/产品设计/股权投资/投行）、**Sites**（agent 建可分享网页应用）、
  **Annotations**（文档内定点指令）。
- **非开发者占 20% 用户，增速是开发者的 3 倍**。

### Claude Code（Anthropic）
- **Plugin 成为规范单元**：skills + subagents + hooks + commands + MCP 打包成版本化、可在市场分享的安装单元。
- **Skills 与 Slash 命令合并**（*Commands and Skills Are Now One Thing*），统一 `SKILL.md` + frontmatter，description 自动触发。
- 子代理 `context: fork` 隔离；新增 post-session hook、`/schedule` 云端定时、safe mode、`/cd`。

---

## 二、对照 Anima：过时 / 不过时

| Anima 已建 | 状态 | 说明 |
|---|---|---|
| Agent 循环 / 压缩(H2/H3) / Verify / 工具 / 权限分级(D3) / 安全(TOOL_SAFETY) | ✅ 不过时 | 基岩，2026 工具仍踩在上面，没白做 |
| Skills(D2) 与 自定义命令(D7) 两套系统 | ⚠️ 过时 | 2026 已合并成一个 SKILL.md |
| Skills/Subagents/Commands/Hooks/MCP 五套独立系统 | ⚠️ 过时 | 2026 范式 = 打包成版本化插件 + 市场 |
| relay→Claude-Sonnet-4.6 写死的模型路由 | ⚠️ 过时 | 模型已全换（GPT-5.3-Codex / Claude Fable 5 / Opus 4.8） |
| "对标 Codex 编程工具"的战略框定 | ⚠️ 过时 | 2026 Codex 已是专业人士操作平台，非编程工具 |

---

## 三、关键反转：Anima 产品方向反而踩对了新浪头

Codex 正往"给非开发者的角色化 AI"跑（角色插件 + 非开发者增速 3 倍）——
这恰好是 Anima 本命方向（陪伴 + 角色化 AI 团队；opc-app「角色化 AI 团队边教边做」）。

**结论**：过时的是"对标 Codex 编程"的**框定**，不是 Anima 的**产品直觉**。
不该追 Codex 的编程工具形态，该顺自己的角色化陪伴方向走。

---

## 四、优化建议（有限、收敛，不打军备竞赛）

> 警告：Codex/Claude Code 背后是巨头按月迭代，小项目做特性对标是必输的军备竞赛。
> 真正该做的是有限的三件事：

1. **合并 Skills 与 Commands**（跟上 2026 范式，D2+D7 本就该一套）。
2. **模型路由去硬编码**（改成可配置模型注册表：新模型来了改配置不改代码，一劳永逸不再过时）。
3. **战略上停止"对标 Codex 编程"，转向夯实角色化陪伴差异点**（巨头结构上不做的护城河）。

**v1.3 厚 harness 依然成立**——"让弱模型也强、不被模型绑架"是穿越版本周期的底层能力，不会过时。

---

## 参考（2026-06 一手信源）
- Codex for (almost) everything — openai.com/index/codex-for-almost-everything/
- OpenAI 新 Codex 白领工具 — techcrunch.com/2026/06/02/
- Introducing GPT-5.3-Codex — openai.com/index/introducing-gpt-5-3-codex/
- Understanding Claude Code's Full Stack 2026 — alexop.dev
- Claude Code changelog — code.claude.com/docs/en/changelog

*文档版本：2026-06-13 v1　作者：Anima Team*
