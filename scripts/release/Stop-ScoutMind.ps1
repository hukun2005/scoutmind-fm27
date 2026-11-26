#Requires -Version 7.0
<#
.SYNOPSIS
    停止由 Start-ScoutMind.ps1 启动的 ScoutMind 后端进程。

.DESCRIPTION
    只停止 PID 文件记录、且命令行确认为本发布包 `app.main:app` 的 Python 进程，
    不会按进程名批量结束 Python/Node，也不会触碰其它应用。

.PARAMETER Root
    发布包根目录；默认根据脚本位置推断。
#>
[CmdletBinding()]
param(
    [string]$Root
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-PackageRoot {
    param([string]$Hint)
    if ($Hint -and (Test-Path -LiteralPath (Join-Path $Hint 'backend/app/main.py'))) {
        return (Resolve-Path -LiteralPath $Hint).Path
    }
    $candidate = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $candidate 'backend/app/main.py')) { return $candidate }
    $parent = Split-Path -Parent $candidate
    if (Test-Path -LiteralPath (Join-Path $parent 'backend/app/main.py')) { return $parent }
    throw '无法定位发布包根目录（需要 backend/app/main.py）。请用 -Root 指定。'
}

$root = Resolve-PackageRoot -Hint $Root
$pidFile = Join-Path $root 'data/scoutmind.pid'

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host '[OK] 没有运行记录（未找到 data/scoutmind.pid），无需停止。' -ForegroundColor Green
    exit 0
}

$raw = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
$processId = 0
if (-not [int]::TryParse($raw, [ref]$processId)) {
    Remove-Item -LiteralPath $pidFile -Force
    Write-Host '[WARN] PID 文件内容无效，已删除记录。' -ForegroundColor Yellow
    exit 0
}

$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $pidFile -Force
    Write-Host "[OK] 进程 $processId 已不存在，已清理 PID 记录。" -ForegroundColor Green
    exit 0
}

# 归属校验：命令行必须包含 uvicorn + app.main:app，可执行文件必须位于本发布包内
$info = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
$commandLine = if ($info) { [string]$info.CommandLine } else { '' }
$executable = if ($info) { [string]$info.ExecutablePath } else { '' }
$looksOurs = $commandLine -match 'app\.main:app' -and $commandLine -match 'uvicorn'
# venv 的 python.exe 在 Windows 上可能把自身重定向到基础解释器，因此以命令行里的发布包路径为准。
$insidePackage = ($commandLine -like "*$root*") -or ($executable -and ($executable -like "$root*"))
if (-not ($looksOurs -and $insidePackage)) {
    Write-Host "[FAIL] PID $processId 不属于本发布包（命令行或路径不匹配），拒绝结束。" -ForegroundColor Red
    Write-Host "       CommandLine: $commandLine"
    Write-Host "       Executable : $executable"
    exit 1
}

Write-Host "==> 停止 ScoutMind（PID $processId）" -ForegroundColor Cyan
Stop-Process -Id $processId -Force
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    Start-Sleep -Milliseconds 300
    if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { break }
}
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Write-Host '[OK] 已停止。' -ForegroundColor Green
