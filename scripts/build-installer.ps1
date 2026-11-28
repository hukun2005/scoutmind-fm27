#requires -Version 5.1
<#
.SYNOPSIS
构建 ScoutMind FM27 Desktop V1.0 的 Windows x64 安装包（Electron + NSIS）。

.DESCRIPTION
1. 构建 Vue 前端生产包
2. 用 PyInstaller 打包 FastAPI 本地服务（客户机器无需 Python）
3. 复用 live-reader 发布产物
4. electron-builder 生成 ScoutMind-FM27-Setup-x64.exe

.PARAMETER Version
应用版本号，默认取 desktop/package.json 的 version。

.PARAMETER SkipFrontend / SkipBackend
跳过对应构建步骤（已构建过时使用）。
#>
param(
    [string]$Version = "",
    [switch]$SkipFrontend,
    [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktop = Join-Path $repo "desktop"
$buildVenv = Join-Path $repo ".build-venv"
$python = Join-Path $buildVenv "Scripts\python.exe"

if (-not $Version) {
    $Version = (Get-Content (Join-Path $desktop "package.json") -Raw | ConvertFrom-Json).version
}

Write-Host "==> ScoutMind FM27 Desktop $Version" -ForegroundColor Cyan

if (-not $SkipFrontend) {
    Write-Host "==> 构建前端" -ForegroundColor Cyan
    Push-Location (Join-Path $repo "frontend")
    try {
        npm ci --no-audit --no-fund
        npm run build
    } finally {
        Pop-Location
    }
}

if (-not $SkipBackend) {
    Write-Host "==> 打包本地服务（PyInstaller）" -ForegroundColor Cyan
    if (-not (Test-Path $python)) { python -m venv $buildVenv }
    & $python -m pip install -r (Join-Path $repo "backend\requirements.txt") --quiet
    & $python -m pip install "pywebview>=6.2,<7" "pyinstaller>=6.22,<7" --quiet

    $work = Join-Path $repo "backend-build\work"
    $dist = Join-Path $repo "backend-build\dist"
    Remove-Item (Join-Path $repo "backend-build") -Recurse -Force -ErrorAction SilentlyContinue
    & $python -m PyInstaller `
        --noconfirm --clean --windowed --name ScoutMindFM27 `
        --paths (Join-Path $repo "backend") `
        --add-data "$repo\frontend\dist;frontend/dist" `
        --add-data "$repo\backend\alembic;backend/alembic" `
        --add-data "$repo\backend\alembic.ini;backend" `
        --collect-submodules app `
        --collect-submodules uvicorn `
        --collect-all langgraph `
        --collect-all langgraph_sdk `
        --collect-all langgraph_checkpoint `
        --collect-all langgraph_checkpoint_sqlite `
        --collect-all langchain_core `
        --collect-all ormsgpack `
        --collect-all webview `
        --collect-all clr_loader `
        --collect-all pythonnet `
        --distpath $dist --workpath $work --specpath (Join-Path $repo "backend-build") `
        (Join-Path $repo "desktop-shell\main.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

    Remove-Item (Join-Path $repo "backend-dist") -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory (Join-Path $repo "backend-dist") | Out-Null
    Copy-Item (Join-Path $dist "ScoutMindFM27") (Join-Path $repo "backend-dist") -Recurse -Force
}

if (-not (Test-Path (Join-Path $repo "release-assets\live-reader\ScoutMind.LiveReader.exe"))) {
    Write-Warning "release-assets\live-reader 缺少 Reader 二进制，安装包将不包含真实数据读取组件"
    New-Item -ItemType Directory (Join-Path $repo "release-assets\live-reader") -Force | Out-Null
}

Write-Host "==> 安装 Electron 构建依赖" -ForegroundColor Cyan
Push-Location $desktop
try {
    $env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
    $env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
    npm install --no-audit --no-fund
    Write-Host "==> 生成安装包（NSIS）" -ForegroundColor Cyan
    npx electron-builder --win nsis
    if ($LASTEXITCODE -ne 0) { throw "electron-builder 构建失败" }
} finally {
    Pop-Location
}

$installer = Join-Path $repo "release\ScoutMind-FM27-Setup-x64.exe"
if (-not (Test-Path $installer)) { throw "未找到安装包：$installer" }
$hash = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower()
"$hash  ScoutMind-FM27-Setup-x64.exe" | Set-Content (Join-Path $repo "release\SHA256SUMS.txt") -Encoding ascii

Write-Host "==> 完成" -ForegroundColor Green
Write-Host ("安装包: {0} ({1:N1} MB)" -f $installer, ((Get-Item $installer).Length / 1MB))
Write-Host "SHA256: $hash"
