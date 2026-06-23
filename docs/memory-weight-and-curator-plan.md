# 记忆权重 + 记忆管家 — 更新计划

> 2026-06-21 与用户收敛定稿。核心是**判断问题**：设计记忆权重，并据此定期裁决"什么留、什么清"。
> 关联：[memory-persona-system-plan.md] · `memory_injector.py`（M3闸门/复合分/M2b升格）·
> `memory_sqlite.py`（演化时间线/向量）· `scholar_worker.py`（守藏周级 SOP）·
> [anima-divinity-redesign] 红线（自我改写=可批准/有界/可逆）。

---

## 〇、一句话

记忆不止一个权重。把**检索权重**（这轮该不该调出来）和**留存权重**（值不值得长期留）
拆开；留存权重的脊梁不是"多重要"，而是**"删了重不重得回来"（删除代价 / 不可重得性）**。
据此让"记忆管家"定期裁决升 / 留 / 降 / 归档。

---

## 一、两个权重，别混（病根：importance 一个数字身兼两职）

| 权重 | 问题 | 何时算 | 现状 |
|---|---|---|---|
| **检索权重** | 这一轮对话该不该把它调出来 | 每轮，跟话题走 | 已有：复合分 = 相关性(M4余弦)+新近度+重要性 |
| **留存权重** | 这条值不值得长期留着 | 定期，跟话题无关 | **空白，本次新增** |

两者必须分离：一条记忆可此刻检索权重低（跟当前话题无关）但留存权重高（是底色）；
反之亦然。混在一起 → "为今天有用而长期留噪音"或"因此刻没用而忘掉底色"。

---

## 二、留存权重的脊梁：删除代价，不是重要性

- "我爸退休前修钟表" → 不重要，但**删了就真没了**，恰是让她"认识你"的细节 → 重留。
- "你在做跨境电商" → 重要，但**能从对话随时重算** → 不必硬留。

**按"重要性"留 = 留一堆正确的废话；按"删了重不重得回来"留 = 留得住"她认识你"那部分。**

---

## 三、留存权重的五个分量

| 分量 | 一句话 | 怎么得出 |
|---|---|---|
| **来源分**（脊梁） | 你主动说/纠正过/吵过架/承诺(D) > 她观察推断 > 系统客套一次性 | 机械（`source` + 分类 A/B/C/D 映射） |
| **复现分** | 跨多次对话反复 > 提一次的 | 机械（向量聚簇命中数，**去掉同次对话内重复**） |
| **解释力** | 能串起你十个行为的洞察 > 孤立事实 | **推理**（LLM 判，= 升格 L1→L2 内核） |
| **衰减（按类）** | 不同类不同半衰期，不一刀切 | 机械（见下表） |
| **印证刷新** | 每次现实再证明一次，衰减时钟归零 | 机械（新增 `last_reinforced`，区别于 `last_accessed`） |

**按类半衰期（起始值，待调）**：

| 类 | 半衰期 | 含义 |
|---|---|---|
| A 身份 / D 关系 / user_profile | ~2 年（近乎不衰减） | 你是谁、你们之间的事 |
| L2 画像洞察 | ~1.5 年 | 蒸出来的"你是什么样的人" |
| B 偏好 / preference / writing_style | ~1 季度（被印证就刷新） | 你怎么干活、口味 |
| C 近期状态 | ~2 周（到期主动重判） | 这阵子忙啥、什么情绪 |

**用户已拍板：底座里"来源分"权重 > "复现分"**（偏不可重得性 = 像重感情的密友，
而非要看几次才当真的观察者；也贴神女"记得你说过的每句要紧话"的位格）。

---

## 四、合成：机械底座 + 推理裁决（= "检索 + 推理"的精确分工）

不线性加权拍系数（假精确）。两层：

1. **底座（机械，天天能跑，不烧 token）**：
   `留存权重 = 来源分 × 按类衰减 × (1 + 复现增益)`，clamp 到 [0,1]。
   两头明摆着的（身份层该留、一次性噪音该清）到此即定。
2. **裁决（推理，周期跑，只管中间地带）**：
   管家只对**落在中间、或检测到矛盾/疑似过时**的记忆调 LLM，判解释力 + 是否过时 + 升降格。
   两头不浪费推理，也省 token。

**输出是四档处置，不是删/不删二元**：
- **升格** C→B/A 或 L1→L2（"这阵子焦虑"反复且没被推翻 → "容易内耗"）
- **保留** 刷新时钟
- **降权** 留着但检索沉底、半衰期缩短
- **归档** 移出活跃区进时间线——**永不真删，可回溯**

---

## 五、三条红线（不守即违背项目宪法 + 合规）

1. **从不真删，只归档**。一切"清理"进 `memory_history` 时间线，可回溯、用户能翻出。
2. **改身份/关系类(A/D)记忆，必须用户点头**。管家只"建议 + 生成待确认项"，由"她"找机会问。
   对齐已有 conflict→问用户范式，对齐 [anima-divinity-redesign]"自我改写=可批准/有界/可逆"。
3. **自动能动的只有无争议项**（C 过期归档、纯冗余合并）；有争议（矛盾、A/D 改写）一律转确认。

---

## 六、分阶段实施 + 改动落点

### Phase 1 — 留存权重底座（机械层，纯函数，可单测）
- 新建 `backend/memory_weight.py`：`HALFLIFE_BY_CATEGORY`、`SOURCE_BASE_BY_CATEGORY`、
  `halflife_for()`、`recency_factor()`、`source_score()`、`retention_weight(entry, recurrence)`。
- `memory_backend.py`：`MemoryEntry` 加 `last_reinforced` 字段 + `to_dict`。
- `memory_sqlite.py`：schema 迁移 `ALTER TABLE memories ADD COLUMN last_reinforced`；
  `_row` 读取；`write()` 新插入时置初值。
- `memory_injector.py`：`_recency_score` 改按 category 取半衰期（替全局 `RECENCY_HALFLIFE_DAYS`）。
- 单测 `tests/test_memory_weight.py`。

### Phase 2 — 接入检索 + 印证刷新
- `_score_topic_relevance` 复合分里 `importance` 项 → 换成 `retention_weight`。
- 记忆被命中/印证时刷新 `last_reinforced`（区别于"被检索"的 `last_accessed`）。
- 跑全量记忆测试确认无回归。

### Phase 3 — 记忆管家周级 SOP
**用户已拍板"全自动静默"**：无争议项静默处理、且全部进时间线可回溯（不真删）。

✅ 已落地（确定性层，不调模型，968 测试绿）：
- `memory_sqlite.py`：新增可回溯归档原语 `_archive_to_history`；把 `archive_stale_c_layer`
  从**硬删**改成**移进时间线**（修了一处违反"不真删"红线的旧行为）；新增 `merge_near_duplicates`
  （同分类纯重复——规整后内容全等——留留存权重最高的一条，其余 reason='merge' 归档）。
- `scholar_worker.py` 新增 `run_weekly_memory_audit()`：归档过时 C 层 + 合并纯重复，返回汇总。
- `websocket_server.py` 注册 + 路由（同 M2b/M10 模式），cron 周一 05:15（紧跟 G1 语体 05:00）。
- `tests/test_memory_audit.py`。

✅ Phase3 子阶段已落地（993 测试全绿）：
- `memory_sqlite.py`：新增 `memory_reviews` 表（迁移兼容）+ `add_review`（对称去重）/
  `list_pending_reviews` / `resolve_review`（resolved/dismissed）/ `find_review_candidates`
  （bigram Jaccard ≥ 0.35，同分类，跳纯重复/已open对，A/D 标 identity_conflict）。
- `scholar_worker.py`：新增 `FLAG_CONFIRMATION_DEF` 工具 + `_flag_for_confirmation` 实现 +
  `run_weekly_review_scan` SOP（候选 → LLM 裁决 → flag 队列，绝不改原记忆）。
  cron 周一05:30，websocket 注册/路由。
- `memory_injector.py`：`format_pending_reviews`（最多2条 surfacing，注入每日灵犀）。
- `tests/test_memory_reviews.py`（16 tests）。

### Phase 4 — 语体"越来越像" ✅ 已落地（993 测试全绿）
- **发现口头禅/起头**（不止固定表）：`_discover_phrases`（跨条文档频次 n-gram）+ `_discover_openers`。
- **语义纹理层**：复盘 LLM 输出切分【微调建议】+【表达习惯】两段；`save_texture` 落库注入 system prompt。
- `parse_review_output` 兼容旧格式。`tests/test_lang_profile.py`（9 new tests，共22）。

---

## 七、待调 / 待定

- [ ] 半衰期与"复现增益"系数小样本调参（Phase 1 给起始值）。
- [x] 无争议清理（C 过期 / 纯冗余）：**用户拍板"全自动静默"**——静默归档可回溯。
- [x] Phase 3 子阶段：矛盾/身份纠偏的"待确认项"——**已落地**（993 测试）。
- [x] Phase 4 语体越来越像——**已落地**（993 测试）。
