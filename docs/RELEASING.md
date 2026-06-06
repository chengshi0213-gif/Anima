# 发版与自动更新指南

> 目标：打一个 tag → CI 自动构建四平台 → 安装包 + `update.json` 自动发布到
> **anima-site**（公开仓库，GitHub Pages 提供下载与更新清单）→ 用户端自动收到更新。

---

## 一、版本号规则（重要）

自动更新靠版本号比较，**每次发版必须同步三处**，否则 updater 认为"已是最新"不触发：

| 文件 | 字段 |
|---|---|
| `src-tauri/tauri.conf.json` | `"version": "x.y.z"` |
| `src-tauri/Cargo.toml` | `version = "x.y.z"` |
| git tag | `vx.y.z` |

三者必须一致（tag 带 `v` 前缀，文件里不带）。

历史教训：v1.1.1~v1.1.4 期间文件里版本号一直停在 `1.1.0`，导致每次构建出来的
应用内部版本都是 1.1.0，自动更新永远无法触发。**改版本号是发版第一步。**

---

## 二、一次性配置：ANIMA_SITE_TOKEN（让 CI 能跨仓库发布）

CI 默认的 `GITHUB_TOKEN` 只能写当前仓库（Anima），无权推送到另一个仓库
（anima-site）。所以需要一个对 anima-site 有写权限的 PAT：

1. 打开 https://github.com/settings/tokens
2. **推荐 Fine-grained token**（更安全）：
   - Repository access → Only select repositories → 勾选 **anima-site**
   - Permissions → Repository permissions → **Contents: Read and write**
   - 生成并复制 token（`github_pat_...`）
   - （也可用 Classic token + `repo` scope，但权限过大不推荐）
3. 到 **Anima** 仓库：Settings → Secrets and variables → Actions → New repository secret
   - Name: `ANIMA_SITE_TOKEN`
   - Value: 粘贴刚才的 token
4. 完成。以后打 tag 即全自动发布。

> 未配置该 secret 时，`publish-release` 任务会**优雅跳过**（仅 warning，不让 CI 变红），
> 此时需手动发布（见下）。

---

## 三、正常发版流程（配好 PAT 后）

```bash
# 1. 改版本号（三处一致）
#    src-tauri/tauri.conf.json, src-tauri/Cargo.toml

# 2. 提交 + 打 tag + 推送
git add -A && git commit -m "release: vX.Y.Z"
git push origin master
git tag vX.Y.Z
git push origin vX.Y.Z
```

CI 自动完成：四平台构建 → Anima release（私有，留存）→ 安装包 + update.json
发布到 anima-site（公开）→ 用户端自动更新。

---

## 四、手动发布（没配 PAT，或想本地补发某个版本）

前提：本地 `gh` 已登录、且对 anima-site 有写权限（`gh auth status` 查看）。

```bash
TAG=vX.Y.Z
VERSION=${TAG#v}

# 1. 从 Anima release 下载安装包 + 签名
gh release download $TAG --repo chengshi0213-gif/Anima --dir ./_pub --pattern "Anima_*" --pattern "*.sig"

# 2. 发布到 anima-site release
gh release create $TAG --repo chengshi0213-gif/anima-site --title "Anima $TAG" --notes "Anima $TAG" || true
gh release upload $TAG --repo chengshi0213-gif/anima-site ./_pub/* --clobber

# 3. 生成 update.json（注意 mac 用 .app.tar.gz，不是 .dmg）
#    签名内容直接读 .sig 文件，URL 指向 anima-site 的 $TAG release
#    （字段格式见 .github/workflows/build.yml 的 Generate update.json 步骤）

# 4. 提交 update.json 到 anima-site 仓库根目录并 push
```

---

## 五、自动更新原理速记

- 应用启动 5 秒后，`src-tauri/src/lib.rs` 后台调 updater，拉取
  `https://chengshi0213-gif.github.io/anima-site/update.json`
- updater 用 `tauri.conf.json` 里的 `pubkey` 校验 `update.json` 中每个平台的
  `signature`（由 `anima-signing.key` 私钥签出，私钥**绝不入库**）
- 版本更高则前端弹"立即更新"条 → `downloadAndInstall()` → `relaunch()`
- 平台 key：`windows-x86_64` / `darwin-aarch64` / `darwin-x86_64`
- **mac 更新包必须是 `.app.tar.gz`**（updater 下载替换的是 app 包），`.dmg` 仅供全新安装
