# Anima — 构建与发布指南

## 目录

1. [开发模式](#开发模式)
2. [生产打包](#生产打包)
3. [Python Sidecar 打包](#python-sidecar-打包)
4. [GitHub Actions 自动发布](#github-actions-自动发布)
5. [开源配置清单](#开源配置清单)

---

## 开发模式

### 前置要求

| 工具 | 版本 | 安装 |
|------|------|------|
| Node.js | ≥ 20 | https://nodejs.org |
| Rust | ≥ 1.80 | https://rustup.rs |
| Python | ≥ 3.10 | https://python.org |

### 快速启动

```powershell
# 克隆后进入项目
cd anima

# 安装依赖（只需一次）
npm install
pip install -r backend/requirements.txt

# 一键开发启动
.\dev.ps1
```

或者手动两步启动：

```powershell
# 终端 1：启动 Python 后端
python backend/websocket_server.py

# 终端 2：启动 Tauri 开发窗口（首次编译约 3-5 分钟）
npm run tauri dev
```

### 配置 API Key

复制配置模板：

```powershell
cp backend/config/config.example.yaml backend/config/config.yaml
```

编辑 `backend/config/config.yaml`，填入你的 DeepSeek API Key：

```yaml
api:
  deepseek_key: "sk-你的key"
```

或者用环境变量（优先级更高）：

```powershell
$env:DEEPSEEK_API_KEY = "sk-你的key"
python backend/websocket_server.py
```

---

## 生产打包

### 第一步：打包 Python 后端为 sidecar

```powershell
# 安装 PyInstaller
pip install pyinstaller

# 打包（Windows）
cd backend
pyinstaller --onefile `
    --name anima-server-x86_64-pc-windows-msvc `
    --add-data "config/config.example.yaml;config" `
    websocket_server.py

# 复制到 Tauri binaries 目录
mkdir -p ..\src-tauri\binaries
cp dist\anima-server-x86_64-pc-windows-msvc.exe ..\src-tauri\binaries\
```

### 第二步：在 tauri.conf.json 中启用 externalBin

`src-tauri/tauri.conf.json` 的 `bundle` 节点加上：

```json
"externalBin": [
  "binaries/anima-server"
]
```

### 第三步：构建 Tauri 安装包

```powershell
cd ..  # 回到 anima 根目录
npm run tauri build
```

输出文件位置：

```
src-tauri/target/release/bundle/
├── nsis/
│   └── Anima_1.0.0_x64-setup.exe   ← Windows 安装包
├── msi/
│   └── Anima_1.0.0_x64.msi         ← Windows MSI
└── (macOS/Linux 同理)
```

---

## Python Sidecar 打包

各平台 sidecar 文件名规则（Tauri 要求）：

| 平台 | 文件名 |
|------|--------|
| Windows x64 | `anima-server-x86_64-pc-windows-msvc.exe` |
| macOS Apple Silicon | `anima-server-aarch64-apple-darwin` |
| macOS Intel | `anima-server-x86_64-apple-darwin` |
| Linux x64 | `anima-server-x86_64-unknown-linux-gnu` |

Rust target triple 用 `rustc -vV | grep host` 查看。

---

## GitHub Actions 自动发布

推送 tag 触发自动构建：

```bash
git tag v1.0.0
git push origin v1.0.0
```

Actions 会自动：
1. 在 Windows/macOS/Linux 三平台并行编译
2. 用 PyInstaller 打包 Python sidecar
3. 用 tauri-action 构建安装包
4. 创建 GitHub Release Draft，上传所有平台的安装包

需要在 GitHub 仓库 Settings → Secrets 中配置：
- `TAURI_SIGNING_PRIVATE_KEY`（可选，用于更新签名）

---

## 开源配置清单

发布到 GitHub 前，确认以下项目：

- [ ] `backend/config/config.yaml` 已加入 `.gitignore`（包含真实 API Key）
- [ ] `backend/data/` 已加入 `.gitignore`（运行时数据）
- [ ] `src-tauri/binaries/` 已加入 `.gitignore`（本地打包产物）
- [ ] `README.md` 包含正确的 GitHub 仓库链接
- [ ] `LICENSE` 年份和作者名称正确
- [ ] 代码中无硬编码的个人信息或路径

---

## 环境变量参考

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 空 |
| `ANTHROPIC_API_KEY` | Anthropic API Key | 空 |
| `ANIMA_DATA_DIR` | 数据目录 | `~/.anima/data` |
| `ANIMA_WORKSPACE` | Agent 工作目录 | `~/.anima/workspace` |
| `OBSIDIAN_VAULT` | Obsidian Vault 路径（可选） | 空 |
| `FEISHU_APP_ID` | 飞书通知（可选） | 空 |
