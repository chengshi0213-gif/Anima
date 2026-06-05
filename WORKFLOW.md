# Anima — 三方协作工作流

Claude × Codex × Hermes 分工协议。

---

## 分工表

```
用户（产品决策）
      │
      ▼
 Claude（本会话）────────────────────────────────────
  │  负责：思考/策略/架构判断/写提示词/评审结果/跨会话记忆
  │
  ├──▶  Codex  exec "prompt"
  │     负责：读代码→改文件→跑测试→提交
  │     适合：功能实现/bug修复/重构/多文件编辑
  │
  └──▶  hermes -z "prompt" --yolo
        负责：调研/文档/记忆/长任务/联网
        适合：竞品分析/知识整理/内容生成
```

---

## 任务决策树

```
收到任务
  │
  ├─ 需要改代码？
  │    └─ YES → Claude 写 Codex prompt → codex exec
  │
  ├─ 需要调研/搜索/写文档？
  │    └─ YES → Claude 写 Hermes prompt → hermes -z
  │
  ├─ 需要架构判断/取舍？
  │    └─ YES → Claude 直接回答（不委托）
  │
  └─ 需要和用户对话确认？
       └─ YES → Claude 直接问用户
```

---

## Codex 调用注意事项

```bash
# 默认只读沙箱 — 只能看，不能改文件
codex exec "prompt"

# 可写模式（需要改文件时必须用这个）
codex exec --approval never --sandbox none "prompt"

# 或交互式（需要人工确认每步操作时）
codex "prompt"
```

**约束写法规范**：提示词里如果说"不改 *_worker.py"，必须同时说清楚例外，
否则 Codex 会严格遵守导致合理改动被拒。

---

## 标准任务模板

### Codex 任务模板

```
## 项目上下文
项目路径：E:\AI\workspace\Anima
架构索引：见 CLAUDE.md
测试命令：cd backend && python -m pytest tests/ -q
JS检查：node --check src/*.js

## 任务
[具体任务描述]

## 目标文件
[列出预期要改的文件]

## 验收标准
[可验证的完成条件]

## 约束
[不能动的文件/不能破坏的行为]
```

### Hermes 任务模板

```
## 任务
[研究/分析/生成目标]

## 输出格式
[表格/报告/列表/Markdown文档]

## 输出位置
[终端输出 / 写入 docs/xxx.md]

## 参考资料
[可用的链接/文件路径]
```

---

## 活跃任务队列

### 🔴 v1.1.1 剩余（Codex）
- [ ] 修复 `shell_run` 的 `format` 子串误杀 bug
- [ ] 重新生成应用图标（`tauri icon src/assets/anima-avatar.png`）

### 🟡 v1.1.1 延期
- [ ] Landing 页改版（内容已变，需全新设计）
- [ ] 群聊功能丰富化（参考扣子3.0，待细聊）

### 🔵 v1.2.0（见 docs/v1.2.0-design.md）
- [ ] M11：MCP 协议 + 异步工具内核
- [ ] M12：异步任务 + 流式执行
- [ ] M13：Git 一等公民 + 项目感知 + TDD 循环
- [ ] M14：权限确认 + Hooks 系统

---

## 协作记录

| 日期 | 任务 | 执行方 | 结果 |
|---|---|---|---|
| 2026-06-05 | v1.1.1 UI整改 | Codex | ✅ 已提交 4ec2f6d |
| 2026-06-05 | v1.1.1 console.html删除 | Claude | ✅ 已提交 2a309b5 |
| 2026-06-05 | CLAUDE.md / .clignore / AGENTS.md / HERMES_RULES.md / WORKFLOW.md | Claude | ✅ 已提交 |
