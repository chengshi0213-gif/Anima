# Anima — Hermes 调用规范

> Hermes 是研究、记忆、长任务层。Claude 通过 `hermes -z "prompt" --yolo` 调用。

---

## 调用语法

```bash
# 单次非交互任务（最常用）
hermes -z "任务描述" --yolo

# 指定模型
hermes -z "任务描述" --yolo -m deepseek-v4-pro

# 带会话名（可续接）
hermes -z "任务描述" --yolo --continue anima-research

# 续接上次同名会话
hermes --continue anima-research
```

---

## 适合给 Hermes 的任务

| 任务类型 | 原因 |
|---|---|
| 竞品/市场调研 | 有联网工具，有记忆，可续接 |
| 文档整理/知识提炼 | 长上下文 + 记忆持久化 |
| 需要跨天持续的研究 | sessions 可跨会话恢复 |
| 批量文件分析 | 不污染 Claude 主上下文 |
| 需要调用多个外部工具 | toolsets 丰富（MCP/web/memory） |
| 生成需要记忆的内容 | 自动写入 memory，下次用得到 |

## 不适合给 Hermes 的任务

| 任务类型 | 原因 | 应该给谁 |
|---|---|---|
| 改 Anima 代码 | Codex 更了解代码上下文 | Codex |
| 架构设计/取舍判断 | 需要和用户对话 | Claude |
| 构建/打包/测试 | 需要访问本地 Tauri 工具链 | Codex |

---

## 会话命名约定

```
anima-research-{主题}      ← 调研类
anima-content-{内容类型}   ← 内容生成类
anima-analysis-{对象}      ← 分析类
```

---

## 输出约定

Hermes 任务完成后，Claude 从输出中提取结论，决定：
- 直接告知用户
- 转成 Codex prompt 执行
- 写入 `docs/` 存档

---

## 示例调用

```bash
# 竞品调研
hermes -z "调研 Replika、Character.AI、Talkie 三款产品的定价策略和核心功能差异，输出对比表格，重点关注国内用户可访问性" --yolo --continue anima-research-competitor

# 技术文档整理
hermes -z "阅读 E:/AI/workspace/Anima/docs/ 下所有 md 文件，提炼出当前版本状态、待办事项和风险点，生成一份项目健康报告" --yolo
```
