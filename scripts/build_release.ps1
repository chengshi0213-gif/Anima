# ============================================================
#  build_release.ps1 — Anima 完整发布构建
#  步骤:
#    1. 安装/更新 Python 依赖
#    2. PyInstaller: backend → anima-server.exe
#    3. cargo tauri build → Anima_x.x.x_x64-setup.exe
#  用法: .\scripts\build_release.ps1
#  输出: src-tauri\target\release\bundle\nsis\
# ============================================================

$ErrorActionPreference = "Stop"
$root    = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$spec    = Join-Path $backend "build\anima-server.spec"
$dist    = Join-Path $backend "dist"
$exe     = Join-Path $dist "anima-server.exe"

Write-Host ""
Write-Host "╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       Anima — Release Build          ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Python 依赖 ───────────────────────────────────────
Write-Host "[1/3] 安装 Python 依赖..." -ForegroundColor Yellow
pip install -r (Join-Path $backend "requirements.txt") -q
if (-not $?) { Write-Error "pip install 失败"; exit 1 }
pip install pyinstaller -q
if (-not $?) { Write-Error "PyInstaller 安装失败"; exit 1 }
Write-Host "      ✓ Python 依赖就绪" -ForegroundColor Green

# ── Step 2: PyInstaller ──────────────────────────────────────
Write-Host ""
Write-Host "[2/3] 打包 Python 后端 → anima-server.exe ..." -ForegroundColor Yellow
Set-Location $backend
pyinstaller $spec --clean --distpath dist --workpath build
if (-not $?) { Write-Error "PyInstaller 失败"; exit 1 }

if (-not (Test-Path $exe)) {
    Write-Error "找不到 $exe，PyInstaller 可能未成功输出"
    exit 1
}
$sz = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "      ✓ anima-server.exe (${sz} MB)" -ForegroundColor Green

# Tauri v2 sidecar 需要 target-triple 后缀的副本
$exeTriple = Join-Path $dist "anima-server-x86_64-pc-windows-msvc.exe"
Copy-Item $exe $exeTriple -Force
Write-Host "      ✓ triple copy: $(Split-Path $exeTriple -Leaf)" -ForegroundColor Gray

# ── Step 3: Tauri ─────────────────────────────────────────────
Write-Host ""
Write-Host "[3/3] 构建 Tauri 应用..." -ForegroundColor Yellow
Set-Location $root
npx tauri build
if (-not $?) { Write-Error "Tauri 构建失败"; exit 1 }

# 找到生成的安装包
$nsis = Get-ChildItem (Join-Path $root "src-tauri\target\release\bundle\nsis\") -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($nsis) {
    $nsisSize = [math]::Round($nsis.Length / 1MB, 1)
    Write-Host "      ✓ 安装包: $($nsis.FullName) (${nsisSize} MB)" -ForegroundColor Green
}

Write-Host ""
Write-Host "╔══════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║        ✓  构建完成！                 ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
if ($nsis) {
    Write-Host "  安装包路径:" -ForegroundColor Cyan
    Write-Host "  $($nsis.FullName)"
}
Write-Host ""
