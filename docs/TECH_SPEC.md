# Anima — 技术规格文档（Tech Spec）
**版本**: v0.1 · **日期**: 2026-05-25

---

## 一、技术栈

| 层 | 技术 | 版本 | 说明 |
|---|---|---|---|
| **桌面壳** | Tauri | v2 | Rust + WebView2，Windows 优先 |
| **前端** | 原生 HTML/CSS/JS | ES2022+ | 无框架，保持轻量；未来可迁移 Vue |
| **后端** | Python + aiohttp | 3.11 / 3.9+ | 单进程异步，所有 Agent 同一端口 |
| **通信** | WebSocket + HTTP REST | — | WS 用于实时对话，REST 用于配置/查询 |
| **记忆存储** | SQLite (FTS5) | stdlib | 本地全文检索，无额外依赖 |
| **调度** | APScheduler | 3.x | 晨间报告、定期 SOP 等定时任务 |
| **打包** | PyInstaller + Tauri bundle | — | Python 后端打包为 sidecar exe |
| **配置** | YAML + 环境变量 | — | 用户配置在 `~/.anima/config.yaml` |

---

## 二、系统架构

```
┌─────────────────────────────────────────────┐
│                  Tauri 壳                    │
│  ┌─────────────────────────────────────┐    │
│  │           WebView2 (前端)            │    │
│  │  index.html / main.js / styles.css  │    │
│  └──────────────┬──────────────────────┘    │
│                 │ WebSocket / HTTP           │
│  ┌──────────────▼──────────────────────┐    │
│  │        anima-server.exe (sidecar)    │    │
│  │         Python + aiohttp             │    │
│  │                                      │    │
│  │  ┌──────────┐  ┌──────────────────┐ │    │
│  │  │ xi_worker│  │  yiyi_worker     │ │    │
│  │  │  Anima   │  │    晞            │ │    │
│  │  └──────────┘  └──────────────────┘ │    │
│  │  ┌──────────┐  ┌──────────────────┐ │    │
│  │  │tianyuan  │  │ scholar_worker   │ │    │
│  │  │  陶朱    │  │    守藏          │ │    │
│  │  └──────────┘  └──────────────────┘ │    │
│  │                                      │    │
│  │  ┌──────────────────────────────┐   │    │
│  │  │       记忆系统               │   │    │
│  │  │  memory_injector (工厂)      │   │    │
│  │  │  memory_sqlite / obsidian    │   │    │
│  │  └──────────────────────────────┘   │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘

数据目录: ~/.anima/
  ├── config.yaml          # 用户配置
  ├── data/
  │   ├── sessions.db      # 聊天历史
  │   ├── memory.db        # 记忆 (FTS5)
  │   ├── logs/            # 运行日志
  │   └── workflows/       # 工作流定义
  ├── skills/              # Skill 文件系统
  ├── workspace/           # Agent 工作区
  └── identity/            # 身份文件（未来 Agent 社交用）
```

---

## 三、端口分配

| 端口 | 用途 | 路径 |
|---|---|---|
| **9100** | WebSocket 主通道 | `/ws/xi`, `/ws/yiyi`, `/ws/tianyuan`, `/ws/shoucang` |
| **9101** | Anima HTTP API（保留，合并到9100） | — |
| **9119** | Dashboard（开发调试用） | `/` |

> **v1.0 决策**：所有 WebSocket 和 HTTP REST 合并到 9100 端口，减少复杂度。

---

## 四、API 端点规范

### WebSocket 协议

连接：`ws://127.0.0.1:9100/ws/{agent_id}`

消息格式（发送）：
```json
{
  "type": "chat",
  "content": "用户消息",
  "model": "DeepSeek-V4-Flash",
  "session_id": "uuid",
  "files": []
}
```

消息格式（接收流）：
```json
{"type": "chunk", "content": "..."}
{"type": "done", "usage": {"tokens": 120}}
{"type": "error", "message": "..."}
```

### REST API

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/config` | 读取配置 |
| POST | `/config` | 更新配置 |
| GET | `/sessions` | 历史会话列表 |
| GET | `/sessions/{id}` | 单个会话详情 |
| POST | `/memory/learn` | 手动写入记忆 |
| GET | `/memory/entries` | 查看记忆列表 |
| GET | `/memory/search` | 搜索记忆 |
| DELETE | `/memory/entries/{id}` | 删除记忆条目 |
| GET | `/memory/backend` | 当前记忆后端 |
| POST | `/memory/backend` | 切换记忆后端 |
| GET | `/skills` | Skill 列表 |
| GET | `/report/daily` | 生成日报 |
| GET | `/report/weekly` | 生成周报 |
| POST | `/webhook/{token}` | 外部触发（Zapier 等）|

---

## 五、记忆系统规范

### 数据模型

```sql
CREATE TABLE memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT NOT NULL,     -- user_profile/preference/note/general
    agent_id    TEXT NOT NULL,     -- xi/yiyi/tianyuan/scholar
    importance  INTEGER DEFAULT 3, -- 1-5
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(key, agent_id)
);

CREATE VIRTUAL TABLE memories_fts USING fts5(key, value, content=memories);
```

### 记忆注入规则

1. 每次对话开始前，读取该 Agent 的相关记忆
2. 按 importance DESC + updated_at DESC 排序
3. 限制总字符数 ≤ 1500 字（避免 context 污染）
4. 格式化后插入 system prompt 末尾

---

## 六、技术债务清单（已知问题）

| 问题 | 优先级 | 计划 |
|---|---|---|
| `websocket_server.py` 单文件超 1700 行 | 中 | v1.1 拆分为路由模块 |
| 前端无打包工具，CSS 有两个文件 | 低 | 合并 styles.css + styles_new_features.css |
| 无单元测试 | 中 | 先写关键路径测试（记忆读写、路由） |
| 错误处理不统一 | 中 | 统一 error response 格式 |
| 日志系统基础 | 低 | 接入 structlog |
| `package-lock.json` 有旧包名 | 低 | `npm install` 后自动修复 |

---

## 七、开发环境

### 启动方式

```bash
# 1. 启动后端（开发模式）
cd E:\Anima\backend
pip install -r requirements.txt
python websocket_server.py

# 2. 启动前端（另一个终端）
cd E:\Anima
npm install
npx tauri dev

# 或使用快捷脚本
.\dev.ps1
```

### 构建发布包

```bash
# 1. 打包 Python 后端
E:\Anima\backend\build\build.bat

# 2. 打包 Tauri
npm run tauri build
```

---

## 八、目录结构规范

```
E:\Anima\
├── src/                    # 前端
│   ├── index.html          # 主界面
│   ├── console.html        # 调试控制台
│   ├── main.js             # 前端逻辑（~3500行，待拆分）
│   ├── styles.css          # 主样式
│   ├── styles_new_features.css  # 待合并
│   └── assets/             # 图标、头像
│
├── backend/                # Python 后端
│   ├── websocket_server.py # 主入口 + 路由（待拆分）
│   ├── xi_worker.py        # Anima
│   ├── yiyi_worker.py      # 晞
│   ├── tianyuan_worker.py  # 陶朱
│   ├── scholar_worker.py   # 守藏
│   ├── agent_base.py       # Agent 基类
│   ├── memory_*.py         # 记忆系统
│   ├── config.py           # 配置中心
│   ├── config/             # YAML 配置文件
│   └── build/              # 打包脚本
│
├── src-tauri/              # Tauri 配置
│   ├── src/lib.rs          # 后端启动逻辑
│   ├── tauri.conf.json     # Tauri 配置
│   └── icons/              # 应用图标
│
├── docs/                   # 工程文档（本目录）
│   ├── PRD.md
│   ├── TECH_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   └── XI_IDENTITY.md
│
└── scripts/                # 工具脚本
```
