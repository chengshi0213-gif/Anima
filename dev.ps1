# Anima — 开发模式快速启动
# 运行: .\dev.ps1

Write-Host "Anima 开发模式启动" -ForegroundColor Yellow
Write-Host ""

# 1. 启动 Python 后端 (port 9100)
$backend = "$PSScriptRoot\backend\websocket_server.py"
Write-Host "启动后端 (port 9100)..." -ForegroundColor Cyan
$pythonProc = Start-Process python -ArgumentList $backend -PassThru -WindowStyle Normal
Write-Host "  PID: $($pythonProc.Id)"

# 等待后端就绪（最多等 10 秒）
$ready = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 1
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:9100/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        $ready = $true; break
    } catch {}
}
if ($ready) { Write-Host "  OK 后端就绪" -ForegroundColor Green }
else        { Write-Host "  WARN 后端未响应" -ForegroundColor Red }

# 2. 启动 Tauri dev 窗口
Write-Host ""
Write-Host "启动 Tauri dev 窗口..." -ForegroundColor Cyan
Write-Host "  首次编译需要 3-5 分钟，请耐心等待"
Write-Host ""
npm run tauri dev
