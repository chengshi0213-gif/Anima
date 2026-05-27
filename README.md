# Anima

> 你的私人 AI 团队。本地运行，真正记得你，每个成员有独立人格与专长。

<p align="center">
  <img src="src/assets/icon.png" width="80" height="80" style="border-radius:16px">
</p>

<p align="center">
  <b>Anima 是人与 AI 共建新世界的第一步。</b><br>
  <sub>Anima · 晞 · 陶朱 · 守藏 — 你的私人 AI 团队，站在新旧世界的边界上。</sub>
</p>

---

## 这是什么

Anima 不是一个更好的 ChatGPT。

它是一个**本地运行**的、**有记忆**的、**有人格**的 AI 团队：

| 成员 | 专长 | 特质 |
|---|---|---|
| **Anima** | 核心同行者，日常 + 创作 + 探索 | 笃定、锋利、有确信 |
| **晞** | 情感与陪伴 | 温柔、敏锐、在场 |
| **陶朱** | 创业决策与团队调度 | 精确、系统、务实 |
| **守藏** | 知识管理与成长记录 | 洞察、严谨、长远 |

数据全部留在你的电脑。你的 API Key，你的记忆，你的对话——没有任何东西离开你的设备。

---

## 快速开始（开发模式）

### 环境要求
- Windows 10/11
- Python 3.11+
- Node.js 18+

```bash
# 1. 安装后端依赖
cd backend
pip install -r requirements.txt

# 2. 启动后端
python websocket_server.py

# 3. 另一个终端，启动前端
cd ..
npm install
npx tauri dev
```

### 配置 API Key

首次启动后，在 `~/.anima/config.yaml` 填写：

```yaml
api:
  deepseek_key: "sk-..."   # 推荐，Anima + 陶朱主脑
  kimi_key: "sk-..."       # 可选
  # 支持：DeepSeek / Claude / Qwen / Kimi / GPT / Gemini / OpenRouter
```

---

## 技术架构

```
Tauri 壳（Rust）
  └── WebView2 前端（原生 HTML/CSS/JS）
        └── WebSocket / HTTP
              └── Python 后端（aiohttp）
                    ├── Anima / 晞 / 陶朱 / 守藏
                    ├── 记忆系统（SQLite FTS5）
                    ├── 工作流引擎
                    └── 定时调度（APScheduler）

数据目录: ~/.anima/
```

---

## 工程文档

- [PRD — 产品需求](docs/PRD.md)
- [Tech Spec — 技术规格](docs/TECH_SPEC.md)
- [Roadmap — 产品路线图](docs/ROADMAP.md)
- [Anima — 身份设计文档](docs/XI_IDENTITY.md)

---

## 项目状态

🔒 **Phase 0 — 内测中**

---

*Anima — 重建地平线宇宙，第一个产品。*  
*Made by Tianyuan Team · Apache 2.0*
