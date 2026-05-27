# ============================================================
#  build_backend.ps1 — 将 Python 后端打包为 anima-server.exe
#  用法: .\scripts\build_backend.ps1
#  输出: backend\dist\anima-server.exe
# ============================================================

$ErrorActionPreference = "Stop"
$root    = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$dist    = Join-Path $backend "dist"
$spec    = Join-Path $backend "build\anima-server.spec"

Write-Host "=== Anima 后端打包 ===" -ForegroundColor Cyan
Write-Host "根目录: $root"

# 1. 安装依赖
Write-Host "`n[1/4] 安装 Python 依赖..." -ForegroundColor Yellow
pip install -r (Join-Path $backend "requirements.txt") -q
if (-not $?) { Write-Error "pip install 失败"; exit 1 }

# 2. 确保 PyInstaller 可用
pip install pyinstaller -q
if (-not $?) { Write-Error "PyInstaller 安装失败"; exit 1 }

# 3. 运行 PyInstaller（使用 spec 文件）
Write-Host "`n[2/4] 运行 PyInstaller 打包..." -ForegroundColor Yellow
Set-Location $backend

pyinstaller $spec --clean --distpath dist --workpath build
if (-not $?) { Write-Error "PyInstaller 打包失败"; exit 1 }

# 4. 验证输出 + 创建 Tauri 需要的 triple 命名副本
$exe     = Join-Path $dist "anima-server.exe"
$exeTrip = Join-Path $dist "anima-server-x86_64-pc-windows-msvc.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "`n[3/4] 打包成功！" -ForegroundColor Green
    Write-Host "  输出: $exe (${size} MB)"
    # Tauri v2 sidecar 要求文件名包含 target triple
    Copy-Item $exe $exeTrip -Force
    Write-Host "  副本: $exeTrip" -ForegroundColor Gray
} else {
    Write-Error "打包失败：找不到输出文件 $exe"
    exit 1
}

# 5. 提示下一步
Write-Host "`n[4/4] 下一步：构建 Tauri 应用" -ForegroundColor Cyan
Write-Host "  cd $root"
Write-Host "  cargo tauri build"
Write-Host ""
