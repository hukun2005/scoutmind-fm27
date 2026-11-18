# 初始化本地开发环境（Windows PowerShell 7+）
# 用法：.\scripts\setup.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host '[1/4] 创建后端虚拟环境 ...'
Push-Location "$root\backend"
if (-not (Test-Path .venv)) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Pop-Location

Write-Host '[2/4] 初始化数据库（Alembic）...'
Push-Location "$root\backend"
& .\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location

Write-Host '[3/4] 安装前端依赖 ...'
Push-Location "$root\frontend"
if (Test-Path package-lock.json) {
    npm ci
} else {
    npm install
}
Pop-Location

Write-Host '[4/4] 导入演示数据（可跳过：不要演示数据时不执行）...'
& "$root\backend\.venv\Scripts\python.exe" "$root\scripts\seed_demo.py"

Write-Host ''
Write-Host '完成。接下来：'
Write-Host '  后端：.\scripts\run-backend.ps1'
Write-Host '  前端：.\scripts\run-frontend.ps1'
