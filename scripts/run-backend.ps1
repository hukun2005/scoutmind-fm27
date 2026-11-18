# 启动 ScoutMind 后端（仅 127.0.0.1）
# 用法：.\scripts\run-backend.ps1 [-Port 8000] [-Reload]
param(
    [int]$Port = 8000,
    [switch]$Reload
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = "$root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "未找到虚拟环境：请先运行 .\scripts\setup.ps1"
}

$arguments = @('-m', 'uvicorn', 'app.main:app', '--app-dir', "$root\backend", '--host', '127.0.0.1', '--port', "$Port")
if ($Reload) { $arguments += '--reload' }

Write-Host "ScoutMind API -> http://127.0.0.1:$Port/docs"
& $python @arguments
