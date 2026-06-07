# 更新日志 (Changelog)

本文件记录 Anima 每个版本的变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 维护约定：每次发版前，先把本次改动写进「未发布」段，发版时改成对应版本号 + 日期。
> 版本号必须三处一致（`tauri.conf.json` / `Cargo.toml` / git tag），详见 `docs/RELEASING.md`。

---

## [未发布]

（暂无）

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
