#Requires -Version 7.0
<#
.SYNOPSIS
    启动 ScoutMind FM27（后端 API + 已构建前端，同一端口）。

.DESCRIPTION
    1. 检查 Windows 与 Python 版本；
    2. 首次运行时在 backend/.venv 创建虚拟环境并安装依赖；
    3. 检查数据目录、数据库并执行 alembic upgrade head；
    4. 启动 uvicorn（仅 127.0.0.1），等待 /api/v1/health；
    5. 输出访问地址与日志路径。

.PARAMETER Port
    API 端口，默认 8000。

.PARAMETER NoBrowser
    不自动打开浏览器。

.PARAMETER Root
    发布包根目录；默认根据脚本位置推断。
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$NoBrowser,
    [string]$Root
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Fail {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    exit 1
}

function Resolve-PackageRoot {
    param([string]$Hint)
    if ($Hint -and (Test-Path -LiteralPath (Join-Path $Hint 'backend/app/main.py'))) {
        return (Resolve-Path -LiteralPath $Hint).Path
    }
    $candidate = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $candidate 'backend/app/main.py')) {
        return $candidate
    }
    $parent = Split-Path -Parent $candidate
    if (Test-Path -LiteralPath (Join-Path $parent 'backend/app/main.py')) {
        return $parent
    }
    Fail "无法定位发布包根目录（需要 backend/app/main.py）。请用 -Root 指定。"
}

$root = Resolve-PackageRoot -Hint $Root
$backend = Join-Path $root 'backend'
$dataDir = Join-Path $root 'data'
$logDir = Join-Path $root 'logs'
$distDir = Join-Path $root 'frontend/dist'
$venvPython = Join-Path $backend '.venv/Scripts/python.exe'
$pidFile = Join-Path $dataDir 'scoutmind.pid'

Write-Host "==> ScoutMind 发布包：$root" -ForegroundColor Cyan

# 1. Windows 版本
$os = Get-CimInstance Win32_OperatingSystem
if ($os.Caption -notmatch 'Windows 1[01]') {
    Write-Host "[WARN] 仅验证过 Windows 10/11，当前：$($os.Caption)" -ForegroundColor Yellow
}
Write-Host "    系统：$($os.Caption) $($os.Version)"

# 2. Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Fail "未找到 python。请安装 Python 3.11+ 并加入 PATH。" }
$versionText = & python --version 2>&1
if ($versionText -notmatch 'Python 3\.(\d+)') { Fail "无法识别 Python 版本：$versionText" }
if ([int]$Matches[1] -lt 11) { Fail "需要 Python 3.11 或更高版本，当前：$versionText" }
Write-Host "    Python：$versionText"

# 3. 目录
foreach ($dir in @($dataDir, $logDir)) {
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}
if (-not (Test-Path -LiteralPath (Join-Path $distDir 'index.html'))) {
    Fail "缺少前端构建产物：$distDir\index.html。请使用发布包中的 frontend/dist。"
}

# 4. 已在运行？
if (Test-Path -LiteralPath $pidFile) {
    $existing = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existing -and (Get-Process -Id ([int]$existing) -ErrorAction SilentlyContinue)) {
        Write-Host "[OK] 已在运行（PID $existing）：http://127.0.0.1:$Port" -ForegroundColor Green
        exit 0
    }
    Remove-Item -LiteralPath $pidFile -Force
}

# 5. 端口（被其它进程占用时直接失败，避免健康检查误连到别的实例）
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owner = ($listener | Select-Object -First 1).OwningProcess
    Fail "端口 $Port 已被 PID $owner 占用。请先停止该进程，或用 -Port 指定其它端口。"
}

# 6. 虚拟环境
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host '==> 首次运行：创建后端虚拟环境并安装依赖（可能需要几分钟）' -ForegroundColor Cyan
    & python -m venv (Join-Path $backend '.venv')
    if ($LASTEXITCODE -ne 0) { Fail "创建虚拟环境失败（退出码 $LASTEXITCODE）。" }
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r (Join-Path $backend 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { Fail "安装后端依赖失败（退出码 $LASTEXITCODE）。" }
}

# 7. 环境变量（子进程继承）
$dbPath = (Join-Path $dataDir 'scoutmind.db') -replace '\\', '/'
$env:SCOUTMIND_DATA_DIR = $dataDir
$env:SCOUTMIND_DATABASE_URL = "sqlite:///$dbPath"
$env:SCOUTMIND_FRONTEND_DIST = $distDir
$env:SCOUTMIND_HOST = '127.0.0.1'
$env:SCOUTMIND_PORT = "$Port"

# 8. 数据库迁移
Write-Host '==> 检查数据库结构（alembic upgrade head）' -ForegroundColor Cyan
Push-Location $backend
try {
    & $venvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Fail "数据库迁移失败（退出码 $LASTEXITCODE）。" }
} finally {
    Pop-Location
}

# 9. 启动后端
$outLog = Join-Path $logDir 'backend.out.log'
$errLog = Join-Path $logDir 'backend.err.log'
Write-Host '==> 启动后端' -ForegroundColor Cyan
# 不保留 Process 对象：带重定向的 Start-Process 若持有对象，父进程退出时会等待子进程的流关闭。
Start-Process -FilePath $venvPython `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--app-dir', $backend, '--host', '127.0.0.1', '--port', "$Port") `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog

# 10. 健康检查
$healthUrl = "http://127.0.0.1:$Port/api/v1/health"
$ready = $false
for ($attempt = 1; $attempt -le 60; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        if ($response.status -eq 'ok') { $ready = $true; break }
    } catch {
        # 启动过程中连接失败是预期情况
    }
}
if (-not $ready) {
    Write-Host '[FAIL] 后端健康检查失败。最后 20 行错误日志：' -ForegroundColor Red
    if (Test-Path -LiteralPath $errLog) { Get-Content -LiteralPath $errLog -Tail 20 }
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    exit 1
}

# 记录真正监听端口的进程（uvicorn 可能是 Start-Process 返回进程的子进程）
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
    Fail "健康检查通过但未找到监听 $Port 的进程，无法写入 PID 记录。"
}
$serverPid = $listener.OwningProcess
Set-Content -LiteralPath $pidFile -Value $serverPid

# 11. 输出
$url = "http://127.0.0.1:$Port"
Write-Host ''
Write-Host "[OK] ScoutMind 已启动：$url" -ForegroundColor Green
Write-Host "     PID：$serverPid"
Write-Host "     API：$url/docs"
Write-Host "     日志：$outLog"
Write-Host "            $errLog"
Write-Host "     数据库：$dataDir\scoutmind.db"
if (-not $NoBrowser) { Start-Process $url }
