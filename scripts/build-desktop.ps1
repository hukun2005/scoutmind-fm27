#requires -Version 5.1
<#
.SYNOPSIS
构建 ScoutMind FM27 Desktop 便携桌面版（单目录、双击即用、无需安装 Python）。

.DESCRIPTION
用 PyInstaller 把 FastAPI 后端、Alembic 迁移与前端生产构建打包成 ScoutMindFM27.exe，
并附带 live-reader 与文档，输出可运行目录和 zip。

.PARAMETER Version
版本号，用于输出目录与 zip 命名，默认取 VERSION.txt。

.PARAMETER OutputRoot
输出根目录，默认 dist-desktop。

.PARAMETER SkipFrontendBuild
跳过 npm run build（前端 dist 已是最新时使用）。
#>
param(
    [string]$Version = "",
    [string]$OutputRoot = (Join-Path $PSScriptRoot "..\dist-desktop"),
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildVenv = Join-Path $repo ".build-venv"
$python = Join-Path $buildVenv "Scripts\python.exe"

if (-not $Version) {
    $versionFile = Join-Path $repo "VERSION.txt"
    $Version = (Select-String -Path $versionFile -Pattern "version=(\S+)").Matches.Groups[1].Value
    if (-not $Version) { throw "无法从 VERSION.txt 解析版本号" }
}

Write-Host "==> 准备构建环境" -ForegroundColor Cyan
if (-not (Test-Path $python)) {
    python -m venv $buildVenv
}
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r (Join-Path $repo "backend\requirements.txt") --quiet
& $python -m pip install "pywebview>=6.2,<7" "pyinstaller>=6.22,<7" --quiet

if (-not $SkipFrontendBuild) {
    Write-Host "==> 构建前端" -ForegroundColor Cyan
    Push-Location (Join-Path $repo "frontend")
    try {
        npm ci --no-audit --no-fund
        npm run build
    } finally {
        Pop-Location
    }
}

Write-Host "==> PyInstaller 打包" -ForegroundColor Cyan
$work = Join-Path $OutputRoot "build"
$dist = Join-Path $OutputRoot "app"
if (Test-Path $OutputRoot) { Remove-Item $OutputRoot -Recurse -Force }

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
    --distpath $dist `
    --workpath $work `
    --specpath $OutputRoot `
    (Join-Path $repo "desktop-shell\main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

Write-Host "==> 组装便携目录" -ForegroundColor Cyan
$package = Join-Path $OutputRoot "ScoutMind-FM27-$Version-Desktop"
New-Item -ItemType Directory $package -Force | Out-Null
Copy-Item (Join-Path $dist "ScoutMindFM27\*") $package -Recurse -Force
New-Item -ItemType Directory (Join-Path $package "data\raw") -Force | Out-Null
New-Item -ItemType Directory (Join-Path $package "logs") -Force | Out-Null

# live-reader 需要 .NET 发布产物；优先复用发布流水线 stage 中的二进制
$liveReader = Join-Path $repo "dist-release\stage\ScoutMind-FM27-$Version\live-reader"
if (Test-Path $liveReader) {
    Copy-Item $liveReader $package -Recurse -Force
} else {
    Write-Warning "未找到 live-reader 发布产物，桌面包将不包含真实数据读取组件：$liveReader"
}

foreach ($doc in 'COMPATIBILITY.md', 'INSTALLATION.md', 'KNOWN_ISSUES.md', 'LICENSE', 'RELEASE_NOTES.md', 'VERSION.txt', 'README-Desktop.txt') {
    $source = if ($doc -eq 'README-Desktop.txt') {
        Join-Path $repo "desktop-shell\README-Desktop.txt"
    } else {
        Join-Path $repo $doc
    }
    if (Test-Path $source) { Copy-Item $source $package -Force }
}

$zip = Join-Path $OutputRoot "ScoutMind-FM27-$Version-Desktop-Windows-x64.zip"
Compress-Archive -Path $package -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  ScoutMind-FM27-$Version-Desktop-Windows-x64.zip" | Set-Content (Join-Path $OutputRoot "SHA256SUMS-Desktop.txt") -Encoding ascii

Write-Host "==> 完成" -ForegroundColor Green
Write-Host "目录: $package"
Write-Host "压缩包: $zip"
Write-Host "SHA256: $hash"
