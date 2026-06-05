# Anima 项目地图

防止反复探索浪费 token。任务开始前先查这里定位目标文件，不要无故 ls/read 整个目录。

---

## 关键文件索引

| 文件 | 一句话作用 | 改动场景 |
|---|---|---|
| `backend/agent_base.py` | ReAct 循环 + 工具分发，`_execute_tool` 是唯一工具调用点 | 改工具执行逻辑、流式、压缩 |
| `backend/capabilities.py` | 能力积木注册表（命脉），`_FACTORIES` 控制有哪些能力 | 加新工具模块 |
| `backend/xi_worker.py` | 主 agent 装配，`CAPS` 列表控制加载哪些能力积木 | 改主 agent 行为/工具集 |
| `backend/orchestrator.py` | delegate/子员工/受控递归，不要轻易改 | 改编排逻辑 |
| `backend/persona.py` | 四人格卡（已合并为 xi），`PERSONAS` dict | 改人格文字/模型默认值 |
| `backend/ws_manager.py` | WS 消息循环，`current_task` + cancel | 改 WS 协议/action |
| `backend/websocket_server.py` | 服务入口，`main()` 装配所有 worker + 路由注册 | 加新路由模块/worker |
| `backend/config.py` | 配置系统，`_get()` 读，`save_user_config()` 写，`~/.anima/config.yaml` | 加新配置项 |
| `backend/economy.py` | 成就 + 灵犀定义，`ACHIEVEMENTS` 列表 | 改成就文案/奖励 |
| `backend/git_safety.py` | checkpoint/rollback，工具包范式样板 | 参考此文件新建工具模块 |
| `backend/routes/config.py` | API Catalog + 设置接口，集成目录范式样板 | 参考此文件新建路由 |
| `backend/routes/economy.py` | 成就/灵犀 HTTP 接口，`_gather_signals()` 汇总信号 | 改成就信号来源 |
| `src/index.html` | 前端壳（1449行），侧栏导航 + 所有 tab-panel | 改导航/面板结构 |
| `src/styles.css` | 所有样式，`:root` 里的 CSS 变量是全站颜色 | 改主题/配色 |
| `src/overview.js` | 总览页 + Skill 成长区 + 成就墙渲染 | 改总览文案/布局 |
| `src/settings.js` | 设置页，含欢迎语/记忆/API 管理/onboarding | 改设置项/欢迎语 |
| `src/main.js` | 全局函数：switchTab/newChat/主题切换 | 改全局导航逻辑 |
| `src/economy.js` | 成就/灵犀前端渲染 | 改成就页 UI |
| `src-tauri/tauri.conf.json` | Tauri 窗口/图标/打包配置 | 改窗口尺寸/标题栏/图标 |
| `.github/workflows/build.yml` | CI 构建 + GitHub Release | 改打包/发布流程 |
| `landing/index.html` | 官网落地页（独立站，米白+金色设计） | 改官网内容/下载链接 |

---

## 子员工分工（7 个，继承 AgentBase）

```
executor_worker.py  — 写代码/文件操作/shell/TDD
writer_worker.py    — 文案/文档/产品方案
reader_worker.py    — 长文/代码库摘要/信息提取
critic_worker.py    — 代码评审/方案评估/挑毛病
researcher_worker.py — 联网调研/竞品/资料搜集
analyst_worker.py   — 数据分析/财务建模/算账
pm_worker.py        — 需求拆解/PRD/排期
```

这 7 个文件**不要轻易改**，在 orchestrator.py 的 `SUBAGENT_FACTORIES` 里注册。

---

## 当前版本状态

- **v1.1.0 已完成**：人格合并（四→Anima）、邀请系统（Supabase zxlsmyzrskkcgmekszgh 新加坡）、语言图谱
- **v1.1.1 待做**：UI 整改（见 docs/ 或与用户确认）
- **v1.2.0 设计稿**：见 `docs/v1.2.0-design.md`，对标 Codex + Claude Code
- **后端测试**：`cd backend && python -m pytest tests/ -q`，194 个用例

---

## 禁止无故读取的路径

```
node_modules/
src-tauri/target/
backend/__pycache__/
backend/dist/
backend/build/
backend/.pytest_cache/
landing/Anima_*.exe
*.pyc
*.pyo
```

---

## 架构核心规律（减少探索的心智模型）

1. **加工具** = 在 `capabilities.py` 加一块积木（`_FACTORIES` 注册），`xi_worker.CAPS` 加一个字符串
2. **加 HTTP 接口** = 在 `routes/` 新建文件，照抄 `routes/config.py` 的 `register(app)` 范式，`websocket_server.py` 里 import + 调用
3. **改人格文字** = 只动 `persona.py` 和 `settings.js` 的欢迎语，不碰 worker 文件
4. **改配置项** = `config.py` 加 `_get("xxx", default)`，`config.example.yaml` 加注释示例
5. **新建工具模块** = 照抄 `git_safety.py` 的结构：`*_TOOL_DEFS` + `build_*_dispatch()`
