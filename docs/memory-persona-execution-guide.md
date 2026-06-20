# Anima 记忆与人格系统 · 执行指示文档

> 配套文档：`memory-persona-system-plan.md`（v3，回答"为什么做/做什么"）、
> `persona-voice-spec.md`（V1 语体设计书，已落地）。
> 本文档回答"按什么顺序做、每步怎么验收"——v3 规划定稿后的执行手册，
> 任务编号/估时/优先级与 plan v3 §七一致，不重复设计动机，只做可执行拆解。

---

## 使用方式

- 每个任务：开工前看"做什么"+"依赖"，做完按"验收"自检。
- 完成后两处打勾：本文档对应 checkbox + plan v3 §七 该行状态改成 ✅。
- 任务粒度 = 一次提交。改完跑对应 `pytest`，全绿再勾。
- 执行中如发现与 plan 设计冲突的实现细节，先用 AskUserQuestion 跟用户对齐，
  不要在执行层悄悄改设计——改了要回写 plan 对应章节，避免文档漂移。

---

## 执行总览（3 批，~38h）

### 阶段一·快赢包（~5.5h）— 现在开始
- [x] V1 初始人格语体定稿（已完成）
- [x] M1 记忆能力积木（remember/recall/forget）— 2.5h — P0（已完成）
- [x] M2a 守藏每日 SOP 定时 — 1h — P0（已完成）
- [x] P1 子员工语言规范统一 — 1.5h — P0（已完成）

### 阶段二（~19.5h）
- [x] M3 写入质量闸门 — 2h — P1（已完成 2026-06-11，305 测试全过）
- [x] M4 语义检索（混合召回）— 6h — P1（已完成 2026-06-11，316 测试全过；本地模型文件待用户放置，未放置前自动降级纯 FTS5）
- [x] M5 话题感知注入（复合分）— 2h — P1（已完成 2026-06-11，322 测试全过；分层预算=画像300+话题相关900+兜底300）
- [x] M8 记忆感知三式 — 3h — P1（已完成 2026-06-11，331 测试全过；时间感+主动想起+矛盾质疑均落地）
- [x] M2b 每周升格 SOP — 2.5h — P1（已完成 2026-06-11，342 测试全过；L2画像洞察标来源事实ID+合并+淘汰≤12条，scheduler周一04:30注册）
- [x] M10 偏好学习管线 — 4h — P1（已完成 2026-06-11，357 测试全过；新增 room.py 作为 D8 最小房间判断 + pref_signals/pref_rules 双表 + 周一04:45偏好学习SOP，仅工作房间注入）

### 阶段三（~11.5h）
- [x] P2 前端"她在做事"呈现 — 3h — P1（已完成 2026-06-11；delegate 步骤改为"她正在调用 XX 能力"角标，沿用能力主题色，不切子员工独立头像/气泡；顺带修复 `.thinking-live-steps` 永久 `display:none` 导致实时步骤不可见的预置 bug）
- [x] M6 灵魂空间 — 4h → 实际~5.5h — P2（已完成 2026-06-12；命盘室历史持久化升级为"完整"方案、"她记得的我"室"改错"降为 MVP 只查看+删除，详见 system-plan.md §5.2"实现说明"）
- [x] M9 命盘→画像桥 — 1.5h — P2（已完成 2026-06-12，详见 system-plan.md §5.1"实现说明"）
- [x] G1 语体靠拢 v2 — 2h — P2（已完成 2026-06-12，详见 system-plan.md §4.2"实现说明"）
- [x] M7 遗忘与时效 — 2h — P2（已完成 2026-06-12，381 测试全过）
- [x] P3 死代码清理 — 0.5h — P2（已完成 2026-06-12）
- [x] P4 人格卡审计 — 0.5h — P2（已完成 2026-06-12，全部声明名实相符，无需代码改动）

---

## 阶段一 · 快赢包

### M1 记忆能力积木（remember / recall / forget）— 2.5h — P0

**做什么**
1. `capabilities.py`：新增 `_memory_cap(agent_id)` 工厂，仿照 `_divination_cap`
   的接线方式（惰性 import，dispatch 接到 `memory_backend` 现成的
   `write`/`search` 接口），注册进 `_FACTORIES["memory"]`。tool_defs 含
   `remember(key, value, category, importance)` / `recall(query)` /
   `forget(key)` 三个工具，category 用 §3.1 的 A/B/C/D 四级
   （A 恒定/B 偏好/C 状态/D 关系）。prompt_fragment 写"什么值得记/不记"
   （§3.1：不记一次性指令/寒暄/可重建信息；健康财务等敏感先问一句）。
2. `xi_worker.py`：`CAPS` 追加 `"memory"`（当前 capabilities.py:183 是
   `["execution", "web", "divination", "orchestration", "mcp"]`）。
3. `persona.py`：补"记下了"示范对话——V1 遗留依赖（见
   `persona-voice-spec.md` §四，"记下了"这条口头禅一直待 M1 才能写进示范
   对话，否则名实不符）。`capabilities=[..., "记忆"]`（persona.py:287）
   届时终于名实相符，本任务不用改这行，P4 会做整体复核。
4. §3.1 写入分级表（A/B/C/D）作为 prompt_fragment 正文；D 关系层显式提示
   "她说错过的话/承诺"也值得记（最容易被忽略但最造人感）。

**依赖**：无（M2a / M3 / M5 / M10 / P4 都在此基础上接活）

**验收**
- 新增 capabilities 测试：mock 后端，覆盖 remember/recall/forget 三个
  dispatch 路径。
- `tests/test_persona.py` 全过（含新增"记下了"示范对话）。
- 手测：对话里说"记一下：我下周三去上海出差"→ 触发 `remember`
  （category=C状态）→ 换种问法能 `recall` 到。

---

### M2a 守藏每日 SOP 定时 — 1h — P0

**做什么**
1. `scheduler.py` 已有通用 `TaskScheduler.add_task(name, agent, prompt,
   trigger_type="cron", trigger_value="HH:MM")`。新增系统级任务：每日
   凌晨 4 点（`trigger_value="04:00"`），`agent="shoucang"`（守藏 worker
   的 agent_id，见 `persona.py:318`），`prompt` 触发"扫描当天对话→提炼
   L1 事实→写入"——`scholar_worker.py` 已有 remember 工具 + 
   `read_chat_history`，本任务只是把它从手动触发变成定时触发。
2. 在启动流程（`main.py` 或对应 startup 钩子）里注册这条系统任务，
   先查 `scheduler.list_tasks()` 是否已存在同名任务，避免重复注册。
3. SOP 跑完后调用 `memory_injector.invalidate_cache()`，让当晚新写入的
   记忆立刻在下次对话生效，不等 5 分钟缓存过期。

**依赖**：M1（守藏 SOP 落盘走的就是 M1 打通的 write 路径；代码层面可与
M1 并行写，联调顺序按 M1→M2a）

**验收**
- 重启后端，`scheduler.list_tasks()` 能看到这条每日任务且 `enabled=True`，
  不会重复注册。
- 手动改 cron 为近期时间触发一次，`run_logs.json` 有成功记录，新增的
  L1 事实条目可被 `recall` 到。

---

### P1 子员工语言规范统一 — 1.5h — P0

**做什么**
1. 从 `_CONVERSATIONAL_STYLE`（persona.py，目前只追加给
   `CORE_PERSONA_IDS`）里提炼一个更小的 `_VOICE_CORE`——只收"去AI味"
   硬条款（禁 markdown 气泡 / 禁感叹号 / 不波浪号颜文字叠字 / 不当网友），
   不收 xi 专属的口头禅、情绪谱、格式边界示范对话（那是"她"的声音，
   子员工不需要）。
2. `compose_base_prompt()`（persona.py:333-336 附近）改为：
   `CORE_PERSONA_IDS` 拿完整 `_CONVERSATIONAL_STYLE`，其余 7 个子员工
   （executor/writer/reader/critic/researcher/analyst/pm 等）拿 `_VOICE_CORE`。
3. 跑 `tests/test_persona.py`，对至少 1-2 个子员工 worker 的 prompt
   组装做检查（确认 `_VOICE_CORE` 片段出现在 prompt 里）。

**依赖**：无（与 M1/M2a 都是 prompt/积木层，互不踩文件，可同批并行做完
一起测）

**验收**
- `tests/test_persona.py` 全过。
- 任选一个子员工（如 writer）prompt 组装结果包含"不用感叹号/不波浪号
  颜文字叠字"等 `_VOICE_CORE` 条款，但**不**包含 xi 专属口头禅清单。
- 对应 plan §九风险："`_VOICE_CORE` 只收去AI味条款，不动角色性格"——
  审查确认没有把 xi 的人格化措辞带进子员工 prompt。

---

## 阶段二

### M3 写入质量闸门 — 2h — P1
**做什么**：`memory_injector.py` 写入路径加三件事——近义 key 合并
（同 category 下相似 key 走 upsert 而非新建）、单会话写入条数上限、
importance 过滤（低于阈值且非 A/D 层不写）。冲突检测：新值与旧值矛盾
时不静默覆盖，返回冲突信息，供 M1 的 `remember` 或守藏 SOP 转成
"咦，你之前说的是 X，现在变了？"的提问（§3.2）。
**依赖**：M1（有 remember 入口才有"写入"可言）
**验收**：单测覆盖近义合并/上限/冲突返回三种路径；§3.2 矛盾处理示例
能在对话中触发提问而非静默覆盖。

### M4 语义检索（混合召回）— 6h — P1
**做什么**：本地 `bge-small`（onnx，纯本地，守"绝不联网"）生成
embedding，`memory_sqlite.py` 加向量表；新增 `memory_embed.py` 封装
编码/相似度计算；检索路径改为 FTS5 ∪ 余弦相似度合并去重。onnxruntime
不可用时自动降级回纯 FTS5（plan §九风险行）。
**依赖**：建议排在 M3 之后（写入路径稳定后再加检索维度），无强制阻塞
**验收**：换种说法问旧事（语义而非关键词重合）能召回；onnxruntime
不可用时自动降级、不报错。

### M5 话题感知注入（复合分）— 2h — P1（依赖 M4）
**做什么**：`memory_injector.py` + `agent_base.py` 注入预算分层——
画像层 always-on ~300 字 + 话题相关 ~900 字（M5）+ 高重要性兜底 ~300 字。
话题相关段排序改**复合分 = 相关性(M4 余弦) + 新近度 + 重要性**加权
（替代现 importance Top-N），治 G5。
**依赖**：M4（"相关性"用的就是 M4 的余弦相似度）
**验收**：换话题后注入内容随话题变化（不再是固定 Top-N 静态清单）；
三个权重项可在调试输出中看到分项得分。

### M8 记忆感知三式 — 3h — P1
**做什么**：相对时间换算（"三个月前你提过一次"）；时效记忆到点主动
想起（依赖 scheduler，C 层带过期字段到点触发提醒）；矛盾质疑（接 M3
的冲突返回，转成自然提问）。对应 §3.4 记忆感知五式中的 3/4/5（1/2 已
由 M1/M5 覆盖）。
**依赖**：M3（矛盾返回）+ M2a 的调度基建（主动想起）
**验收**：§3.4 五式逐条手测过一遍，五行全部有真实对话示例可演示。

### M2b 每周升格 SOP — 2.5h — P1
**做什么**：`scholar_worker.py` 新增每周任务（与 M2a 共用 scheduler
注册模式），从 L1 事实簇用 LLM 提炼 L2 画像洞察，写入
`memory_injector.py` 的 always-on 画像层（≤12 条，标来源事实 ID，
含合并淘汰逻辑防膨胀）。
**依赖**：M2a（复用每日 SOP 积累的 L1 事实 + scheduler 注册模式）
**验收**：跑一次升格后，画像层注入内容出现"标来源"的 L2 条目；来源 ID
可在记忆列表里追溯到对应 L1 事实。

### M10 偏好学习管线（v3 新增，第⑦层）— 4h — P1
**做什么**：新增 `pref_learning.py`，采集三类隐式信号（编辑 diff /
吐槽 / 采纳）入 `memory_sqlite.py`；周级任务（复用 M2b 的 SOP 框架与
排期）从 diff 对用 LLM 抽 E 程序层偏好规则——按领域分桶（文案/代码/
PPT/命盘解读各一组）、标来源 diff、单领域样本 <5 不抽、每域上限 ≤8 条。
规则 always-on 注入**工作房间**生成上下文（`agent_base.py`，受 D8
房间门控，日常房间不注入）。与 B 偏好层冲突时先问不静默覆盖（§4.4 纪律）。
**依赖**：M2b（复用其周级 SOP 框架与排期；E 程序层规则是 L2 画像之外
的第二条 always-on 注入，编排顺序见下方"跨任务编排提醒"）
**验收**：模拟一次"产出 A → 用户改成 B"的 diff，周任务跑完后 E 程序层
出现对应规则；同一规则不跨领域生效（文案规则不影响代码生成）；日常
房间对话确认未注入 E 层规则。

---

## 阶段三

### P2 前端"她在做事"呈现 — 3h — P1
**做什么**：`src/state.js` / `src/chat.js` / `src/styles.css`，delegate
时前端显示"她正在调用 XX 能力"而非切到子员工独立头像/气泡，弱化
"一群 AI"观感。**建议体验完阶段一、二后再定稿**（plan §八）。
**依赖**：无强依赖，产品体验上建议排在阶段二之后

### M6 灵魂空间 — 4h → 实际~5.5h — P2 ✅已完成（2026-06-12）
**做什么**：带密码档案馆页面（二次验证复用 `user_auth.py` PBKDF2），
三室——我的命盘 / 她记得的我（M2b 产出的 L2 画像审计界面，原 M6 的
记忆管理升级于此）/ 我们的时刻（D 关系层时间线）。密码门 0.5h + 三室
页面 3.5h。
**依赖**：M2b（"她记得的我"室需要 L2 画像数据）
**落地说明**：新增 `backend/divination_history.py`（排盘历史持久化，
原 plan 未含，命盘室"历次解读记录可回看"需要它）+ 3 个 API 端点；
"她记得的我"室"改错"降为 MVP（只查看+删除，不新增编辑端点）。两处
均经 AskUserQuestion 与用户对齐，详见 system-plan.md §5.2"实现说明"。

### M9 命盘→画像桥 — 1.5h — P2 ✅已完成（2026-06-12）
**做什么**：`cap_divination.py` + `scholar_worker.py`，命理解读结论
转写为 L2 画像条目（来源=命理，置信=待验证），措辞"我猜你是……"而非
"你就是……"；后续互动验证后置信升级或修正留痕。
**依赖**：M2b（写入同一套 L2 画像结构）
**落地说明**：新增工具 `record_chart_insight(trait, insight)`
（`cap_divination.py`，第4个命理工具，挂到 `divination_dispatch`），
内部调 `write_l2_insight(importance=2)` 标记"待验证"先验；
`run_weekly_promotion` prompt 新增对 `importance<=2` 的命理先验 L2
条目的吻合升级/相悖修正指令（3b）。新增 3 测试 + 更新
`test_yiyi_worker.py` 工具清单断言，360 测试全过。按预估 1.5h 完成，
未发现与本节设计的偏差。

### G1 语体靠拢 v2 — 2h — P2 ✅已完成（2026-06-12）
**做什么**：`lang_profile.py` 特征面扩展（emoji 率/长度分布/术语习惯），
三成原则与禁区（脏话/火星文不跟、标点纪律不破）写进注入提示；每周 LLM
语体复盘与 M2b 合并跑，产出"她该怎么微调"。
**依赖**：M2b（合并跑同一个周任务）
**落地说明**：`lang_profile.py` 的 `_analyze()` 新增三个特征维度
（`emoji_rate`/`len_distribution`/`en_mix_rate`）；`get_profile_block()`
升级为包含用户特征描述 + 三成原则（"靠近三成，七成保持自己"）+ 禁区清单
（"脏话/火星文/叠字卖萌不跟、标点纪律不破"）+ LLM 语体建议（如有）的
完整注入块。新增 `save_llm_advice()` 供每周复盘写入建议。
`scholar_worker.py` 新增 `run_weekly_lang_review()` 每周语体复盘 SOP
（周一 05:00，紧跟 M2b 04:30 + M10 04:45），从 `lang_profile` 特征 +
近期消息样本用 LLM 产出"她该怎么微调"建议，存回 `lang_profile.json`，
下次对话时通过 `get_profile_block()` 注入 system prompt。
`websocket_server.py` 接好新任务注册 + trigger 路由。
新增 13 个测试（`tests/test_lang_profile.py`），全量 373 passed。
按预估 2h 内完成。

### M7 遗忘与时效 — 2h — P2 ✅已完成（2026-06-12）
**做什么**：`memory_sqlite.py` + `memory_injector.py`，`last_accessed` +
衰减因子 + 180 天归档，C 状态层为主要对象。
**依赖**：建议排在 M3 之后（写入路径稳定后再做衰减），无强制阻塞
**落地说明**：`memory_backend.MemoryEntry` 新增 `last_accessed` 字段（写入时
NULL，被注入/检索命中时由 `touch_accessed` 刷新为当前时间）；`memory_sqlite.py`
新增 `last_accessed TEXT` 列（含自动迁移）+ `touch_accessed(entry_ids)` 批量
刷新 + `archive_stale_c_layer(days=180)` 归档超时 C 层；`memory_injector.py`
的 `_recency_score` 优先取 `last_accessed`（fallback `updated_at`），
`get_memory_injection` 完成选择后自动 touch，新增 `run_archival()` 供
daily SOP 调用；`scholar_worker.run_daily_sop()` 每晚执行归档。
新增 8 个测试（`tests/test_memory_decay.py`），全量 381 测试全过。

### P3 死代码清理 — 0.5h — P2 ✅已完成（2026-06-12）
**做什么**：`src/styles.css` `src/tokens.css` 三子人格残留变量/规则
清理。
**依赖**：无（建议放最后，避免和 P2 的前端改动冲突）
**落地说明**：删除 4 处死 CSS——`styles.css` 的 `--yiyi`/`--tianyuan`/
`--shoucang` 变量（3行）、`.yiyi-bg`/`.tianyuan-bg`/`.shoucang-bg` 类（3行）、
`#composer-yiyi, #composer-tianyuan, #composer-shoucang` 选择器（从复合选择器
中移除，保留 `#composer-xi`）；`tokens.css` 的 `--persona-yiyi`/
`--persona-tianyuan`/`--persona-shoucang` 别名（3行）。grep 确认 JS/HTML
中无任何引用这些类名/变量的代码，executor/writer/reader/critic 相关 CSS
仍保留（有活跃引用）。381 测试全过。

**补充清理（2026-06-12 复核）**：复核发现 P3 当时遗漏了三套
`body[data-agent="yiyi/tianyuan/tianyuan-team/shoucang"]` 主题变量块
（styles.css ~27行）+ 对应的 `.agent-name`/`.welcome-name` 书法字体规则
（3行）+ 陪伴模式署名颜色规则（1行，引用 yiyi/tianyuan）。`chat.js` 的
`AGENT_THEME_MAP` 早已只剩 `xi`/`executor`/`writer`/`reader`/`critic`，
`document.body.dataset.agent` 不可能再被设为这些值，故确认死代码并删除。
xi 主题块 + 注释保留并简化（"四套主题"改回"Anima=米黄神女光明"单一描述）。
381 测试全过（纯 CSS 改动不影响 pytest）。

### P4 人格卡审计 — 0.5h — P2 ✅已完成（2026-06-12）
**做什么**：`persona.py` 通篇审计每个 PersonaCard 的 `capabilities`
声明与 `CAPS`/`_FACTORIES` 实际工具一一对应，解决 G11 名实不符（M1
落地后"记忆"声明终于有真工具，但要确认其余声明如"组队""命理排盘"
等也都对得上）。
**依赖**：M1
**落地说明**：逐一对照 4 张人格卡（xi/yiyi/tianyuan/shoucang）的
`capabilities` 声明 vs 实际 `_FACTORIES`/`CAPS`/worker `tool_defs`：
- xi 6项全部名实相符（G11"记忆"已由 M1 解决）；`mcp` 在 CAPS 中但作为
  动态元能力不列入面向用户的声明，合理
- yiyi 4项全部对应 `DIVINATION_TOOL_DEFS`（M9 新增的 `record_chart_insight`
  是命理工作流内部工具，不算独立面向用户的能力）
- tianyuan 4项全部对应实际工具（web_search/orchestration/shell_run 等）
- shoucang 4项全部对应实际工具（M10 的 pref 工具是内部 SOP，不算独立能力）
**结论**：全部声明名实相符，**无需代码改动**。381 测试无变化。

---

## 跨任务编排提醒

- **M10 落地说明（与原计划的实现差异）**：原计划把 E 程序层偏好规则
  插在"画像层 → E层 → 话题相关个人记忆"之间。实际实现里
  `agent_base.py` 的 `memory_ctx` 已经是 `get_memory_injection()`（画像+
  话题相关+重要提醒，三者合一的字符串）+ `get_memory_self_description()`
  的整体结果，E 层改为**追加在这个整体结果之后**（`memory_ctx +=
  pref_learning.get_work_room_injection(self.name)`），不拆 `memory_injector.py`
  的三层预算逻辑。对 LLM 看到的最终顺序影响很小（E层仍在画像/相关记忆
  之后、project_ctx 之前），且不影响 M10 验收标准（仅工作房间注入/按
  领域分桶/不跨域）。v1.2.2 D8 完整落地时如需精确插槽顺序，再统一调整。
- **M10 的 D8 依赖**：完整 D8（房间 register 联动等）尚未实现，M10 落地
  时新增了最小版 `room.py`——`room.get_room_type()` 仅依据
  `memory_injector.get_active_project()` 是否绑定项目区分"work"/"daily"，
  作为 D8 的最小基础。完整 D8 落地时在此基础上扩展，不冲突。
- M2a / M2b / M10 三个周期任务最终共用 scheduler 的同一类"系统任务"
  注册模式——M2a 先把模式立好，M2b/M10 复用，避免三套重复脚手架。
  **M2a 落地的具体模式（M2b/M10 直接复用）**：
  1. 幂等注册用 `scheduler.add_task_if_missing(name, agent, prompt,
     trigger_type, trigger_value)`（新增，scheduler.py）——按 name 去重，
     启动时调一次即可，不用自己写 `list_tasks()` 查重循环。
  2. 若任务需要"日期感知的多步流程 + 完成后副作用"（如 invalidate_cache），
     不要把整个 prompt 塞进 `add_task`：在对应 worker 上定义
     `run_xxx_sop()`（同步方法，内部 `asyncio.new_event_loop()` 跑，
     副作用写在方法末尾），再在 `_run_agent` 里用一个 `XXX_TRIGGER`
     哨兵 prompt 常量特例路由到 `asyncio.to_thread(srv.worker.run_xxx_sop)`。
     M2a 的 `DAILY_SOP_TASK_NAME` / `DAILY_SOP_TRIGGER` / `DAILY_SOP_CRON`
     常量定义在 `scholar_worker.py`，可参照。
  3. **顺手修了一个全局 bug**：`scheduler._execute_task` 和
     `file_watcher._on_event` 原先对 `_run_fn` 返回值做 `output[:2000]`，
     但 `_run_agent` 实际返回 `AgentBase.run()` 的 dict——任何已注册的
     定时/监视任务执行后落日志这一步都会 TypeError。已在 `scheduler.py`
     新增 `result_to_text()` 摊平 dict→str 并修了 `_execute_task`；
     `file_watcher.py` 同款 bug **未修**（不在 M2a 范围，已 spawn 后台任务）。
- 任务做完别忘了回写 plan v3 §七表格状态列，和本文档对应 checkbox。

---

*执行指示文档 — 2026-06-10。基于 `memory-persona-system-plan.md` v3
§七/§八拆解，结合代码实查（`capabilities.py` `_FACTORIES` /
`scheduler.py` `TaskScheduler` / `memory_backend.py` write|search /
`persona.py` capabilities 声明 + agent_id="shoucang"）确认落点。*
