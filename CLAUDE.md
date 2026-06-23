# Anima 项目地图

防止反复探索浪费 token。任务开始前先查这里定位目标文件，不要无故 ls/read 整个目录。
更完整的设计文档在 `docs/PROJECT_MAP.md`。

---

## 当前版本状态（2026-06-23）

- **当前版本**：v1.3.1（已发布，Release 在 anima-site 仓库）
- **测试数量**：993 个用例（`cd backend && python -m pytest tests/ -q`）
- **后端启动**：`cd backend && C:\Python314\python.exe websocket_server.py`，端口 9100
- **Python 路径**：`C:\Python314\python.exe`（用这个，不要用 `python` 或 `python3`）

---

## 双站点部署

| 站点 | 地址 | 仓库 | 服务器 |
|---|---|---|---|
| **国内** | https://animaos.cn | `chengshi0213-gif/anima-site` | 腾讯云 124.221.216.23（OpenCloudOS 9.6，Nginx） |
| **国外** | https://chengshi0213-gif.github.io/anima-site | `chengshi0213-gif/anima-site` | GitHub Pages |

自动更新端点：`https://animaos.cn/update.json`（dialog=true，有弹窗提示）。
服务器 SSH：`ssh -i C:\Users\lenovo\.ssh\anima_rsa_pem root@124.221.216.23`
站点路径：`/var/www/anima-site`，更新方式：`git pull origin main`
anima-site 更新后需在服务器 git pull 才能同步到国内站。

---

## 关键文件索引

### 后端核心
| 文件 | 一句话作用 | 改动场景 |
|---|---|---|
| `backend/websocket_server.py` | 服务入口，装配所有 worker + 路由注册 + cron 注册 | 加新路由/worker/cron |
| `backend/agent_base.py` | ReAct 循环 + 工具分发，`_execute_tool` 是唯一工具调用点 | 改工具执行逻辑、流式、压缩 |
| `backend/ws_manager.py` | WS 消息循环，`current_task` + cancel | 改 WS 协议/action |
| `backend/persona.py` | 四人格卡（`PERSONAS` dict），统一事实来源 | 改人格文字/模型默认值 |
| `backend/config.py` | 配置系统，`~/.anima/config.yaml`，`_get()` 读 | 加新配置项 |
| `backend/capabilities.py` | 能力积木注册表，`_FACTORIES` 控制有哪些能力 | 加新工具模块 |
| `backend/xi_worker.py` | 主 agent（Anima），`CAPS` 控制加载哪些能力积木 | 改主 agent 行为 |
| `backend/orchestrator.py` | delegate/子员工/受控递归，不要轻易改 | 改编排逻辑 |
| `backend/economy.py` | 成就 + 灵犀定义，`ACHIEVEMENTS` 列表 | 改成就文案/奖励 |

### 记忆系统（Phase 1-4，993 测试，2026-06-23 落地）
| 文件 | 一句话作用 |
|---|---|
| `backend/memory_weight.py` | 留存权重纯函数：来源分/按类半衰期/复现增益/合成公式 |
| `backend/memory_sqlite.py` | SQLite 后端，含 `memory_reviews` 矛盾队列、`find_review_candidates`（bigram Jaccard） |
| `backend/memory_backend.py` | `MemoryEntry` 数据类，含 `last_reinforced` 字段 |
| `backend/memory_injector.py` | 检索复合分（留存权重）+ `format_pending_reviews` 矛盾 surfacing |
| `backend/scholar_worker.py` | 守藏：周级记忆管家 SOP + 矛盾 LLM 巡检 + 语体复盘（双段格式） |
| `backend/lang_profile.py` | 语体分析：`_discover_phrases`/`_discover_openers`/语义纹理层 `save_texture` |

### 邀请系统（A-G 已落地）
| 文件 | 一句话作用 |
|---|---|
| `backend/invite.py` | 邀请码逻辑：verify/activate/generate，连 Supabase |
| `backend/invite_mailer.py` | 邮箱管家：IMAP 轮询 animaos@139.com → 自动铸码 → SMTP 回信 |
| `backend/routes/invite.py` | 邀请码 HTTP 路由（/invite/check、/invite/verify 等） |

### 前端
| 文件 | 一句话作用 |
|---|---|
| `src/index.html` | 前端壳，侧栏导航 + 所有 tab-panel |
| `src/styles.css` | 所有样式，`:root` 里的 CSS 变量是全站颜色 |
| `src/main.js` | 全局函数：switchTab/newChat/主题切换 |
| `src/settings.js` | 设置页 |
| `src/invite-gate.js` | 结缘码门 + 我的邀请码面板 |
| `landing/index.html` | 官网落地页（米白+金色），含"申请结缘码"按钮和 apply() |
| `src-tauri/tauri.conf.json` | Tauri 配置（版本号、更新端点 animaos.cn、签名公钥） |
| `.github/workflows/build.yml` | CI 构建 + GitHub Release |

---

## 子员工分工（7 个，继承 AgentBase）

```
executor_worker.py   — 写代码/文件操作/shell/TDD
writer_worker.py     — 文案/文档/产品方案
reader_worker.py     — 长文/代码库摘要/信息提取
critic_worker.py     — 代码评审/方案评估/挑毛病
researcher_worker.py — 联网调研/竞品/资料搜集
analyst_worker.py    — 数据分析/财务建模/算账
pm_worker.py         — 需求拆解/PRD/排期
```

在 `orchestrator.py` 的 `SUBAGENT_FACTORIES` 里注册，不要轻易改。

---

## 架构核心规律

1. **加工具** = `capabilities.py` 加积木（`_FACTORIES`）+ `xi_worker.CAPS` 加字符串
2. **加 HTTP 接口** = `routes/` 新建文件，照抄 `routes/config.py` 的 `register(app)` 范式，在 `websocket_server.py` 里 import + 调用
3. **改人格文字** = 只动 `persona.py`，不碰 worker 文件
4. **加新 cron** = `scholar_worker.py` 加方法 + `websocket_server.py` 里 `_scheduler.add_task_if_missing`
5. **新建工具模块** = 照抄 `git_safety.py` 的结构：`*_TOOL_DEFS` + `build_*_dispatch()`
6. **部署更新** = 改 `anima-site` → push GitHub → 服务器 `git pull` 同步国内

---

## 记忆系统架构要点

- **两个权重**：检索权重（每轮，跟话题走）vs 留存权重（定期，跟话题无关）
- **留存权重 = 来源分 × 按类衰减 × (1+复现增益)**，clamp [0,1]
- **按类半衰期**：A/D ~730天 | L2 ~540天 | B ~90天 | C ~14天
- **周级 SOP 时序**（周一凌晨）：M2b 04:30 → M10 04:45 → G1 语体 05:00 → 记忆体检 05:15 → 矛盾巡检 05:30
- **矛盾队列**：`memory_reviews` 表，bigram Jaccard ≥ 0.35 触发，A/D 类标 `identity_conflict`，每日最多 surfacing 2 条
- **红线**：从不真删只归档到 `memory_history`；A/D 类改写必须 human-in-loop

---

## Supabase（邀请系统）

- **Project ref**：`zxlsmyzrskkcgmekszgh`（新加坡，免费层）
- **表**：`invite_codes`、`activations`、`user_quota`
- **码格式**：`ANIMA-XXXX-XXXX`
- **落地页申请**：用户填邮箱 → Vercel API `anima-invite-api.vercel.app/api/apply-invite` → 自动发码

---

## 发版流程

1. 改 `src-tauri/tauri.conf.json` 版本号
2. `cargo tauri build --target x86_64-pc-windows-msvc`（需要 `backend/dist/anima-server.exe` 存在）
3. 用 `tmp_sign/anima_NEW.key` + 密码（密码管理器："Anima Tauri 签名密钥密码"）签名 exe
4. 更新 `anima-site/update.json` 里三个平台的 signature 字段（用 gh api 或直接 push）
5. 推送到 GitHub，服务器执行 `git pull` 同步国内

---

## 禁止无故读取的路径

```
node_modules/
src-tauri/target/
backend/__pycache__/
backend/dist/
backend/build/
backend/.pytest_cache/
tmp_sign/*.exe
tmp_sign/*.tar.gz
*.pyc *.pyo
```
