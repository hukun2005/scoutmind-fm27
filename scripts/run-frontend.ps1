# 启动 ScoutMind 前端开发服务器
# 用法：.\scripts\run-frontend.ps1 [-Port 5173]
param([int]$Port = 5173)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$root\frontend\node_modules")) {
    throw "未安装前端依赖：请先运行 .\scripts\setup.ps1"
}

Push-Location "$root\frontend"
try {
    Write-Host "ScoutMind Web -> http://127.0.0.1:$Port"
    npm run dev -- --port $Port --host 127.0.0.1
} finally {
    Pop-Location
}
