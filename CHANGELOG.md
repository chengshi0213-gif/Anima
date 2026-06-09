# 更新日志 (Changelog)

本文件记录 Anima 每个版本的变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 维护约定：每次发版前，先把本次改动写进「未发布」段，发版时改成对应版本号 + 日期。
> 版本号必须三处一致（`tauri.conf.json` / `Cargo.toml` / git tag），详见 `docs/RELEASING.md`。

---

## [未发布]

（暂无）

---

## [1.2.0] - 2026-06-09

### 新增 (Added)

**生产力北极星 · 四支柱全落地**

- **② MCP 内核**（commit `b5c8e26` + `f7e9e88`）：
  完整 MCP 客户端（`mcp_client.py`）支持 stdio/SSE/HTTP，工具路由接入 `_execute_tool`
  唯一咽喉；设置页新增只读状态面板（已连 Server / 工具数 / 每 Server 折叠工具列表）。
- **④ 设计体系 D1+D2**（commits `84c0cc4` → `dc7aaf2`）：
  `tokens.css` 语义词汇表（`--color-*` / `--persona-*` / `--shadow-*` / `--ease-*`）；
  全新 `components.css` 组件层：MessageBubble 工艺重做（代码块/复制/微弹入场）、
  ThinkingSteps 工具展开卡、输入工具栏工艺重构、OrbCenter 氤氲 WebGL 光雾、
  ConfirmCard 危险操作确认卡（三档风险色，AA 对比度通过）。
- **① 异步流式**（commit `fe3a3a6`）：
  upgrade-in-place 零闪烁方案：流式气泡直接原地升级为最终消息，不销毁重建；
  打字光标 `.msg-cursor` + 呼吸光环 `anima-stream-pulse`；debounce Markdown 渲染（150ms）。
- **③ 工作流运行时 W1+W2**（commits `7f95457` + `044c053`）：
  W1：Drawflow 可视化画布节点 GSAP 入场动画 + 实时执行态（`setNodeExecState` running/done/error）；
  W2：`wfDynamoRun` 完全自洽重写——直接 `POST /workflow/ai_build`，
  dynamo bar 按钮 loading 态防双击，内联 `#wfDynamoStatus` 状态行可见（取代隐藏面板），
  成功后 520ms 等 GSAP 动画完成自动触发 `wfRun()`。

### 改进 (Changed)
- **内核三部曲**（commits `d2f0674` / `9adb655`）：
  异步 `_execute_tool` + 任务注册表断线重连（M12）+ 危险操作确认/Hooks（M14），
  全部挂在唯一咽喉，默认 off 零行为变化。
- **`agent_base.py` 拆分**（commit `2924fbd`）：
  从 711 行消除红线 → 457 行；
  `AgentCompressMixin`（历史压缩落盘）→ `agent_compress.py`；
  `AgentLoggingMixin`（结构化日志 + 飞书推送）→ `agent_logging.py`。

---

## [1.1.9] - 2026-06-07

### 新增 (Added)
- **网页申请结缘码改为排队制**：原"立即返回"模式因 139 邮箱限流频繁失败，
  改为用户网页提交邮箱后进入队列，由本机邮箱管家轮询、自动铸码并发信，
  端到端验证可用（commit `cadd0f1`）。
- **Onboarding「让 Anima 认识你」**：新增自由书写环节，首次见面时把用户的
  自我描述写入 `user_profile` 记忆，Anima 第一句对话即能体现"已经了解你"
  （commit `51911e7`）。
- **Onboarding「认识一下」名片化**：合并原"认识 AI 团队"与"称呼"两步为一步——
  Anima 一句自我介绍 + 用户自己的头像上传（圆形选择器+本地预览）与名字输入，
  同时用作 Anima 对用户的称呼（`user_address.xi`）与未来社交身份（`user.name`）。
  引导步骤从 6 步精简回 5 步。后端新增 `GET/POST /setup/avatar`，头像仅存于
  本机磁盘（`~/.anima/data/avatar_user.*`），全程不外传（commit `0d5759f`）。

### 修复 (Fixed)
- **陪伴模式：灵体光球与对话内容重叠**：`#companionCenter` 此前永久悬浮在聊天区
  上方，开始对话后会与消息气泡视觉碰撞。现监听聊天区内容变化，一旦出现真实
  消息即让光球淡出，把空间让给对话本身（commit `7dd49ad`）。
- **陪伴模式：语音输入按钮位置/样式**：原右下角悬浮圆形按钮突兀，现迁入聊天
  输入框工具栏，与上传/记忆按钮同款图标样式，录音态保留呼吸动画提示
  （commit `7dd49ad`）。

---

## [1.1.8] - 2026-06-07

> 累积修复版。**取代从未发布的 v1.1.7**（该 tag 已打但未构建发布；版本号不复用，故跳到 1.1.8）。
> 用户上一个能装到的版本是 v1.1.6，升级到 1.1.8 将一并获得以下两项修复。

### 修复 (Fixed)
- **后端启动即崩溃（致命）**：`backend/persona.py` 中 `tianyuan` 人格的 prompt 模板残留
  `{user_name}` 占位符，但该人格 `address_key="investor"`，`compose_base_prompt()`
  格式化时缺少 `user_name` 实参 → `KeyError: 'user_name'` → 未捕获异常 → sidecar
  每次启动都崩。这是 v1.1.6 出现的「连接中…卡死 / 后端无响应 / 崩溃提示横幅」的根因。
  修复：将该占位符改为 `{investor}`，与同模板其余文案一致。
- **邀请邮箱管家 IMAP/SMTP 握手失败**：`backend/invite_mailer.py` 连接 139 等老牌邮箱时，
  Python 默认 SSL 上下文过严，握手报 `[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]`，导致"测试连接"
  和自动收发码全部失败。修复：新增 `_mail_ssl_context()`（放宽到 `SECLEVEL=1`），
  应用到 IMAP/SMTP 连接与发信的全部三处。已用 `animaos@139.com` 端到端实测：
  自动收申请邮件 → 铸码 → 回信发码全链路打通。
- **历史记录删除完全失效**：旧 sidecar 二进制早于 DELETE 路由加入的时间编译，运行时
  `DELETE /sessions/{id}` 返回 405 Method Not Allowed + CORS 拦截，点删除「完全没反应」。
  修复：重新打包包含 DELETE 路由的 sidecar；前端改用 document 级事件委托
  （避免 SVG 子元素点击漏检）+ 乐观更新（点击瞬间淡出）+ 失败 toast 反馈。
  已实测：DELETE 返回 200、CORS 预检放行 DELETE，端到端可用。

### 维护 (Maintenance)
- 清理源码树中临时打包产物（`backend/dist_new*`、`build_tmp*`、`.exe.bak`）。
- 将已验证的 sidecar 二进制同步进官方位置 `backend/dist/`，消除「下次构建捡到崩溃版」的隐患。
- 新建本 CHANGELOG。

---

## [1.1.7] - 未发布（已跳过）

- tag 已创建并推送，但从未构建发布。所含「历史删除事件委托重构」已并入 1.1.8。

---

## [1.1.6] - 2026-06-06

### 变更 (Changed)
- 人格印记清洁：用户可见区域全部移除旧人格名（晞 / 陶朱 / 守藏），统一对外呈现为「Anima」，
  行为风格完整保留（`persona.py` / `memory_injector.py` / `economy.py` / `index.html`）。
- 「人格世界皮肤」文案改为「定制皮肤」。

### 修复 (Fixed)
- 更新 updater 签名公钥（原私钥丢失，改用新密钥对）。v1.1.4 → v1.1.6 需手动安装，
  v1.1.6 起恢复自动更新能力。

---

## [1.1.5] - 2026-06-06

### 修复 (Fixed)
- 修正版本号长期停留在 1.1.0 的问题（v1.1.1~v1.1.4 期间文件内版本号未同步），
  该问题曾导致自动更新永远判定「已是最新」而不触发。
- `update.json` 改用动态 URL；macOS 产物改用 `.app.tar.gz`。

---

## 更早版本

- **1.1.1** — UI 整改 + 项目配置
- **1.1.0** — 人格合并（四 → 一）+ 邀请系统 + 语言图谱
