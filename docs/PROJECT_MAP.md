# Anima 项目地图与导航

> 一次扫描，长期复用。改了结构请同步本文件。
> 最后更新：2026-06-20 · 对应版本 v1.3.1（master）

---

## 0. 一句话定位

Anima 是一个 **Tauri v2 桌面应用**：前端 = 原生 JS（无打包器），后端 = Python（aiohttp + WebSocket），通过 PyInstaller 打成 `anima-server` sidecar 随桌面壳分发。产品形态 = 一个有人格的 AI 伙伴「她」，下挂 8 个角色 Worker、记忆系统、技能/工作流、命理子系统，以及 v1.3 的"厚 harness"（让弱模型也能可靠干活）。

**技术栈**：Tauri 2 / Rust 壳（极薄，223 行）· Python 3 后端（~21k 行，81 个模块）· 原生 ES Module 前端（20 个 JS）· SQLite + Obsidian Vault 双记忆后端 · Supabase（邀请码）。

---

## 1. 启动与请求流（boot flow）

```
桌面壳 (src-tauri/src/lib.rs)
   └─ spawn sidecar:  anima_server_main.py        # PyInstaller 入口
        ├─ 修中文/空格路径 + Windows UTF-8 编码     # 关键兼容修复
        ├─ log_config.setup_logging()
        └─ websocket_server.main()                 # ← 真正的装配中心
             ├─ migrate_encrypt_secrets()          # 明文 API Key → 加密
             ├─ crash_reporter 装 asyncio 异常钩子
             ├─ init_builtin_skills() / MCPManager.boot()
             ├─ 创建 8 个 WorkerServer（见 §3）
             ├─ /ws/{agent} WebSocket 端点
             ├─ routes/*.register(app)             # HTTP 路由自注册（见 §5）
             ├─ scheduler + file_watcher           # 定时/文件触发 SOP
             └─ feishu_bot / wechat_bot / invite_mailer 按配置启动
```

- **HTTP/WS 端口**：`config.PORT_WS`，监听 `127.0.0.1`。
- **健康检查**：`/health` · **API 文档**：`/docs`（Swagger）+ `/openapi.json`。
- **前端↔后端**：`src/ws.js` 连 `ws://127.0.0.1:<port>/ws/<agent>`。

---

## 2. 顶层目录地图

| 路径 | 作用 |
|---|---|
| `backend/` | Python 后端，全部业务逻辑（81 个根模块 + 5 个子包） |
| `src/` | 前端 ES Module（无打包器，`index.html` 直接 import） |
| `src-tauri/` | Tauri/Rust 桌面壳（`src/lib.rs` 启动 sidecar） |
| `docs/` | 设计/执行/规划文档（21 篇） |
| `landing/` | 落地页 |
| `scripts/` | 构建/签名脚本 |
| `.github/workflows/build.yml` | CI：`v*` tag 触发，跨平台 PyInstaller + 发 Release |
| `backend/eval/` | v1.3 Eval 评测脊柱（13 任务消融） |
| `backend/skills_bundle/minglijushi` | 命理蒸馏语料（命理居士古籍） |

**根目录治理文档**：`README` · `CLAUDE.md`（AI 协作规约）· `AGENTS.md` · `HERMES_RULES.md` · `WORKFLOW.md` · `CHANGELOG.md`。

---

## 3. 八个 Agent 角色（人格 Worker）

在 `websocket_server.py` 显式装配为 WorkerServer，各有独立 WS 端点：

| agent_id | 类 | 文件 | 角色 |
|---|---|---|---|
| `xi` | XiWorker | `xi_worker.py` | **私人助理 = 核心「她」**（日常房间） |
| `yiyi` | YiyiWorker | `yiyi_worker.py` | 情感伙伴 × 命理魔女 |
| `tianyuan` | TianyuanWorker | `tianyuan_worker.py` | 陶朱 CEO（调度+搜索+shell） |
| `shoucang` | ShoucangWorker | `scholar_worker.py` | 守藏：知识/成长管理，跑每日+每周 SOP |
| `executor` | ExecutorWorker | `executor_worker.py` | 执行者/工程师（TDD 编程） |
| `writer` | WriterWorker | `writer_worker.py` | 写手 |
| `reader` | ReaderWorker | `reader_worker.py` | 阅读者 |
| `critic` | CriticWorker | `critic_worker.py` | 评审 |

> ⚠️ `analyst_worker.py` `pm_worker.py` `researcher_worker.py` 三个「陶朱子员工」已写好但**未在 servers 装配**，由 `orchestrator.py` 经 `SUBAGENT_FACTORIES` 字符串名动态加载（懒加载破循环依赖），不直接对外开 WS 端点。因无静态 import，CI 打包靠 `build.yml` 的 `--hidden-import` 保它们进冻结二进制（见 §9 R1）。改这三者的模块名/路径时，务必同步 `SUBAGENT_FACTORIES` 与 `--hidden-import`。

---

## 4. 后端模块地图（按职责分组）

### 4.1 Agent 内核（基类 + Mixin 组合）
| 模块 | 职责 |
|---|---|
| `agent_base.py` | AgentBase 员工基类（所有 Worker 继承） |
| `agent_tools.py` | 工具执行咽喉（AgentToolGateMixin） |
| `agent_compress.py` | 历史压缩 / 异步落盘摘要（v1.3 F2 三档渐进压缩） |
| `agent_resilience.py` | 循环级错误恢复（H6 + v1.3 F3 容错 JSON 解析） |
| `agent_logging.py` | 结构化日志 + 飞书通知 |
| `orchestrator.py` | 陶朱编排层（多 Worker 协作，M6+M8） |

### 4.2 v1.3 厚 Harness（让弱模型可靠）
| 模块 | Phase |
|---|---|
| `verify_gate.py` | **V** Plan-Execute-Verify 闸门 |
| `failure_memory.py` | **R** 跨会话失败记忆（负向：别再用上次那招硬撞） |
| `solution_memory.py` | **P3** 跨会话解法记忆 / hindsight note（正向：这类错可解、N 轮内修过；v1.3.1） |
| `harness_evolution.py` | **P2** Harness 自演化提案（读失败+解法记忆→排序的"该长什么工具/中间件"建议，`python -m harness_evolution`；v1.3.1） |
| `code_index.py` | **L** 代码定位层（locate + AST find_symbol + SHA256 增量索引） |
| `code_intel.py` | 代码智能工具 B1-B4（AST 优先，regex 回退） |
| `agentless_pipeline.py` | **D** 确定性三段管道（locate→patch→verify） |
| `backend/eval/` | **E** Eval 评测脊柱（`python -m eval`，13 任务消融）；`eval/ablation_demo.py` = 闸门消融离线判别力自检（v1.3.1） |

### 4.3 记忆与检索
| 模块 | 职责 |
|---|---|
| `memory_backend.py` | 记忆后端抽象层 |
| `memory_sqlite.py` / `memory_obsidian.py` | 两个后端实现（SQLite / Obsidian Vault） |
| `memory_injector.py` | 注入门面 + 后端工厂 |
| `memory_embed.py` | 本地语义向量编码（M4） |
| `memory_import.py` | Transfer Memory（从别的 AI 导入记忆） |
| `project_memory.py` | 项目记忆（对标 Claude Code 的 CLAUDE.md，A1） |
| `knowledge_base.py` | 本地 RAG 核心 |
| `search_engine.py` | FTS5 全文跨会话搜索 |

### 4.4 人格 / 能力 / 成长
| 模块 | 职责 |
|---|---|
| `persona.py` | 人格卡框架（M2） |
| `capabilities.py` | 能力积木（轻量 profile 结构） |
| `room.py` | 房间感知（日常/工作两房间，D8） |
| `pref_learning.py` | 偏好学习管线（M10） |
| `lang_profile.py` | 用户语言图谱 |
| `economy.py` | 成就 + 灵犀经济（养成系统） |
| `onboarding.py` | 新用户首次体验 FTUE |

### 4.5 工具层
| 模块 | 职责 |
|---|---|
| `native_tools.py` | 网络/IO 原生工具 |
| `computer_tools.py` | 桌面操作（截图/鼠标/键盘）+ 安全护栏 |
| `git_tools.py` / `git_safety.py` | Git 六件套 / 改动安全网（M9） |
| `websearch.py` | 统一联网检索（M4） |
| `file_watcher.py` | watchdog 封装（文件变更触发 SOP） |
| `task_runner.py` / `task_registry.py` | 后台长命令 / 异步任务注册表（M12） |
| `scheduler.py` | APScheduler 定时任务 |

### 4.6 Skill / 工作流 / 自定义扩展
| 模块 | 职责 |
|---|---|
| `skill_manager.py` | Skill 管理系统（最大模块，1232 行） |
| `community_skills.py` | 社区/精选 Skill 包（70 个） |
| `custom_agent.py` | `.anima/agents/*.md` 自定义子代理（D5） |
| `custom_commands.py` | `.anima/commands/*.md` 快捷命令（D7） |
| `workflow_ai.py` / `workflow_engine.py` / `workflow_manager.py` | AI 搭流 / 执行引擎 / 模板管理（M10） |
| `mcp_client.py` | MCP 客户端（M11） |

### 4.7 安全 / 权限 / 账户
| 模块 | 职责 |
|---|---|
| `permission.py` | 权限分级 readonly/confirm/acceptEdits/auto（D3） |
| `confirm.py` | 危险操作确认 ConfirmBroker（M14） |
| `hooks.py` | pre_tool / post_tool 钩子（M14） |
| `path_sandbox.py` | 文件访问护栏 |
| `secret_box.py` / `wechat_crypto.py` | 透明密钥加密 / 微信回调加解密 |
| `user_auth.py` | 本地密码登录（离线） |
| `membership.py` | 会员系统（激活码 + 权限） |
| `invite.py` / `invite_mailer.py` | 邀请码引擎（Supabase） / 邮箱自动发码 |

### 4.8 集成 / 通知 / 运维
| 模块 | 职责 |
|---|---|
| `feishu_bot.py` | 飞书双向机器人（长连接，免公网 URL） |
| `wechat_bot.py` | 企业微信 / 公众号双向接入（回调模式） |
| `notifier.py` | 飞书 / 钉钉 Webhook 推送 |
| `crash_reporter.py` | 本地崩溃上报与诊断 |
| `report_generator.py` | 日报 / 周报生成 |
| `usage_tracker.py` | 从 JSONL 日志聚合 API 用量 |

### 4.9 配置 / 基础设施
| 模块 | 职责 |
|---|---|
| `config.py` | **集中配置（被 import 29 次的中枢）** |
| `log_config.py` | 中央日志配置 |
| `anima_cli.py` | 命令行入口 |
| `openapi_spec.py` | OpenAPI 3.0 规格 + Swagger UI |
| `ws_manager.py` | WorkerServer：每个 Agent 的 WS 连接管理器 |

### 4.10 命理子系统
| 路径 | 职责 |
|---|---|
| `cap_divination.py` | 命理能力门面（八字 + 紫微） |
| `divination_history.py` | 排盘历史存档（灵魂空间「我的命盘」） |
| `divination/bazi_engine.py` `bazi_enrich.py` | 八字引擎（lunar-python） |
| `divination/ziwei_engine.py` | 紫微引擎（iztro-py 适配） |
| `divination/almanac.py` | 黄历 |
| `divination/tarot.py` `tarot_deck.py` | 塔罗（公版 RWS 牌图） |
| `divination/daily.py` | 今日运势 |
| `divination/interpret.py` `interpret_data.py` | 解读引擎 + 蒸馏语料 |
| `divination/render.py` | 命盘海报渲染 |

---

## 5. HTTP 路由（`backend/routes/`，各自 `register(app)`）

`core` · `auth` · `login` · `config` · `data` · `services` · `knowledge` · `workflow` · `economy` · `invite` · `tasks` · `mcp` · `coding`

---

## 6. 前端模块地图（`src/`，无打包器）

| 文件 | 职责 |
|---|---|
| `index.html` / `main.js` | 入口 + 总装配（main.js v2.0） |
| `ws.js` / `state.js` | WebSocket 客户端 / 全局状态 |
| `companion.js` | **双层架构：陪伴模式（极简）↔ 工作模式** |
| `soul.js` | 陪伴中心「灵体」（WebGL，有机质感 + 声纹） |
| `soulspace.js` | 灵魂空间（M6） |
| `chat.js` | 对话界面 |
| `lingxi.js` / `economy.js` | 灵犀 / 成就经济 UI |
| `workflow.js` / `workflow-canvas.js` | 工作流（Drawflow 节点画布，n8n/扣子风） |
| `divination-card.js` / `divination-viz.js` | 今日运势卡 + 命盘海报 / 三大命理可视化 |
| `mcp-panel.js` | MCP 面板 |
| `overview.js` / `settings.js` | 概览 / 设置 |
| `auth.js` / `invite-gate.js` | 本地登录门控 / 结缘码门 |
| `anim.js` / `error-boundary.js` | 动画 / 全局错误边界 |
| `tokens.css` `styles.css` `components.css` `divination-card.css` | 设计令牌 + 样式 |

---

## 7. 测试与评测

- **单元/属性测试**：`backend/tests/`，64 个 `test_*.py`，**910 用例全绿**。含 Hypothesis 属性测试 + 紫微 golden 差分。
- **Eval 消融**：`python -m eval --model <m> --label <l>`，13 任务量化 harness 各 Phase 增益。报告落 `backend/eval/reports/`。

---

## 8. 运行时数据落点

| 位置 | 内容 |
|---|---|
| `~/.anima/tmp/` | PyInstaller 解压目录（避中文路径坑） |
| `backend/Anima-Vault/` | Obsidian 记忆 Vault（运行时，已 gitignore） |
| `backend/config/*.yaml/json` | 敏感配置（gitignore，仅 `*.example.*` 入库） |
| `<data_dir>/.anima_index/` | code_index 持久化缓存（R3，gitignore） |
| `*.db` | SQLite（记忆/会话/FTS，gitignore） |
| Supabase `zxlsmyzrskkcgmekszgh`（新加坡） | 邀请码表 |

---

## 9. 结构整改记录（2026-06-20，方案见 `docs/refactor-plan.md`）

整改北极星 = **更可靠**；硬约束 = 本环境无法验证 PyInstaller 冻结二进制，故高风险物理分包暂缓。

| # | 问题 | 处置 | 说明 |
|---|---|---|---|
| R1 | **扩展 Worker 不进冻结包**（analyst/pm/researcher 仅动态加载，CI `--onefile` 不收 → 打包版调用即崩） | ✅ 已修 | `build.yml` 四条 pyinstaller 加 `--hidden-import`（纯增量，安全），CI 下次构建实测 |
| R2 | 版本号三处漂移（清单 1.2.3 / 横幅 1.0.0 / tag 1.3.0） | ✅ 已修 | 三清单→1.3.0；新增 `config.ANIMA_VERSION` 单一真源，横幅引用 |
| R3 | 32 个 `.code_index_*.json` 糊在仓库根 | ✅ 已修 | 索引收归 `_DATA_DIR/.anima_index/`；清残留；`.gitignore` 补目录 |
| R4 | 签名私钥贴身仓库根 | ✅ 已验 | `.gitignore` 已 `anima-signing.key` + `*.key` 双重覆盖；不物理移动（免破签名脚本） |
| R5 | `config.py` god module（import×29，45 符号） | ⛔ 否决 | 集中配置中枢化是其职责；拆分引入循环 import 风险、收益低，违背"更可靠" |
| R6 | 后端 81 文件物理分包（`workers/` `memory/` …） | 🕒 暂缓 | 冻结二进制不可本环境验证 + worker 簇动态 import 高危 + 导航已由本图兜底。未来执行前置：本机 PyInstaller 冒烟 + 逐簇迁移。详见 refactor-plan §R6 |

---

## 10. 导航速查

| 我想… | 去看 |
|---|---|
| 改后端启动/装配 | `backend/websocket_server.py` |
| 加一个 HTTP 接口 | `backend/routes/` 选模块 + `register(app)` |
| 改某个角色行为 | `backend/<role>_worker.py`（§3 表） |
| 改 Agent 通用能力（压缩/工具/恢复） | `backend/agent_*.py` |
| 调记忆系统 | `backend/memory_*.py` + `memory_injector.py` |
| 调命理 | `backend/divination/` + `cap_divination.py` |
| 改前端某面板 | `src/<面板>.js`（§6 表） |
| 改配置项 | `backend/config.py`（注意牵连面） |
| 看/加测试 | `backend/tests/test_*.py` |
| 跑评测 | `python -m eval`（`backend/eval/`） |
| 发版 | 推 `v*` tag → `.github/workflows/build.yml` |
