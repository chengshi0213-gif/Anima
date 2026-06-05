# Anima — Codex 工作规则

> 本文件补充全局 `~/.codex/AGENTS.md`。项目架构和文件索引见 `CLAUDE.md`。
> 有冲突时，以本文件和用户当前要求为准。

---

## 项目验证命令

```bash
# 后端测试（必跑，194 个用例）
cd backend && python -m pytest tests/ -q

# 前端语法检查
node --check src/*.js

# Tauri debug 构建（只验证能编译，不打包）
npm exec tauri -- build --debug --no-bundle
```

**每次改完代码，至少跑前两条。Tauri 构建仅在改 src-tauri/ 时需要。**

---

## 禁区（不动这些文件）

```
backend/agent_base.py        ← ReAct 核心，改错全挂
backend/capabilities.py      ← 能力积木，改了测试就红
backend/orchestrator.py      ← 子员工编排，受控递归逻辑
backend/persona.py           ← 人格卡，只改文字不改结构
backend/*_worker.py          ← 所有子员工（7个），不要轻易改
src-tauri/src/               ← Rust 层，不碰
```

---

## 改动范围守则

- **只改前端** → 不需要重启后端，`node --check src/*.js` 即可
- **改后端路由** → 照抄 `routes/config.py` 的 `register(app)` 范式
- **改工具** → 先看 `capabilities.py`，照抄 `git_safety.py` 的工具包结构
- **改配置项** → 在 `config.py` 加 `_get("xxx", default)`，同步更新 `config/config.example.yaml`
- **改成就文案** → 只动 `backend/economy.py` 的 `ACHIEVEMENTS` 列表

---

## 头像路径约定

所有 Anima 头像引用统一用：`/assets/anima-avatar.png`（绝对路径，Tauri 自动解析）

---

## Git 约定

- commit message 格式：`类型: 一句话描述`
- 类型：`feat` / `fix` / `chore` / `refactor` / `docs`
- 不要 `git push`，不要 `git reset --hard`，不要动 `.github/workflows/`

---

## Windows 环境提醒

- shell 命令走 PowerShell 或 Git Bash，不用 cmd
- 路径分隔符用 `/` 或 `\\`，不要单反斜杠
- Python 命令用 `python`（不是 `python3`）
