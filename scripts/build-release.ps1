#Requires -Version 7.0
<#
.SYNOPSIS
    构建 ScoutMind FM27 Windows 发布候选包（目录 + ZIP + SHA256）。

.DESCRIPTION
    1. 前端生产构建（vue-tsc + vite build），只复制 dist，不带 node_modules；
    2. 复制后端源码（app / alembic / requirements），不带虚拟环境与本地数据库；
    3. 发布 Native Reader 与 Desktop Agent（自包含单文件 exe）；
    4. 复制运行脚本、配置示例、安装与发布文档；
    5. 生成 zip 与 SHA256SUMS.txt，并验证 zip 可解压、关键文件齐全。

.PARAMETER Version
    发布版本号，默认 3.2.9.2。

.PARAMETER OutputRoot
    产物目录，默认 <repo>/dist-release。

.PARAMETER SkipFrontendBuild
    复用已有 frontend/dist。

.PARAMETER SkipNativePublish
    复用已有 publish/win-x64（不重新执行 dotnet publish）。
#>
[CmdletBinding()]
param(
    [string]$Version = '3.2.9.2',
    [string]$OutputRoot,
    [switch]$SkipFrontendBuild,
    [switch]$SkipNativePublish
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Fail { param([string]$Message) Write-Host "[FAIL] $Message" -ForegroundColor Red; exit 1 }

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'backend/app/main.py'))) {
    Fail "脚本必须位于仓库 scripts/ 目录：$PSScriptRoot"
}
if (-not $OutputRoot) { $OutputRoot = Join-Path $repoRoot 'dist-release' }

$packageName = "ScoutMind-FM27-V$Version"
$stageRoot = Join-Path $OutputRoot 'stage'
$packageRoot = Join-Path $stageRoot $packageName
$zipPath = Join-Path $OutputRoot "$packageName-Windows-x64.zip"

Write-Step "产物目录：$OutputRoot"
if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

# 1. 前端
$distSource = Join-Path $repoRoot 'frontend/dist'
if (-not $SkipFrontendBuild) {
    Write-Step '前端生产构建'
    $frontend = Join-Path $repoRoot 'frontend'
    if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules'))) {
        Push-Location $frontend
        try { & npm ci; if ($LASTEXITCODE -ne 0) { Fail 'npm ci 失败' } } finally { Pop-Location }
    }
    Push-Location $frontend
    try { & npm run build; if ($LASTEXITCODE -ne 0) { Fail 'npm run build 失败' } } finally { Pop-Location }
}
if (-not (Test-Path -LiteralPath (Join-Path $distSource 'index.html'))) { Fail "缺少前端构建产物：$distSource" }
Write-Step '复制前端 dist'
New-Item -ItemType Directory -Path (Join-Path $packageRoot 'frontend') -Force | Out-Null
Copy-Item -LiteralPath $distSource -Destination (Join-Path $packageRoot 'frontend/dist') -Recurse -Force

# 2. 后端
Write-Step '复制后端源码'
$backendTarget = Join-Path $packageRoot 'backend'
New-Item -ItemType Directory -Path $backendTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot 'backend/app') -Destination (Join-Path $backendTarget 'app') -Recurse -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'backend/alembic') -Destination (Join-Path $backendTarget 'alembic') -Recurse -Force
foreach ($file in @('alembic.ini', 'requirements.txt')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot "backend/$file") -Destination (Join-Path $backendTarget $file) -Force
}
Get-ChildItem -LiteralPath $backendTarget -Recurse -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path (Join-Path $backendTarget 'data') -Force | Out-Null

# 3. Native Reader + Agent
$nativeTarget = Join-Path $packageRoot 'live-reader'
if ($SkipNativePublish) {
    Write-Step '复用已有 publish/win-x64'
    $existing = Join-Path $repoRoot 'publish/win-x64'
    if (-not (Test-Path -LiteralPath (Join-Path $existing 'ScoutMind.LiveReader.exe'))) {
        Fail "SkipNativePublish 需要已有产物：$existing"
    }
    Copy-Item -LiteralPath $existing -Destination $nativeTarget -Recurse -Force
} else {
    Write-Step '发布 Native Reader 与 Desktop Agent'
    & (Join-Path $repoRoot 'scripts/publish-windows.ps1') -OutputRoot $nativeTarget
    if ($LASTEXITCODE -ne 0) { Fail 'publish-windows.ps1 失败' }
}

# 4. 配置、脚本、文档
Write-Step '复制配置、运行脚本与文档'
New-Item -ItemType Directory -Path (Join-Path $packageRoot 'config') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot 'config/app.example.json') -Destination (Join-Path $packageRoot 'config/app.example.json') -Force

New-Item -ItemType Directory -Path (Join-Path $packageRoot 'scripts') -Force | Out-Null
foreach ($script in @('Start-ScoutMind.ps1', 'Stop-ScoutMind.ps1', 'Check-Environment.ps1', 'Backup-Database.ps1', 'backup_sqlite.py')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot "scripts/release/$script") -Destination (Join-Path $packageRoot "scripts/$script") -Force
}

$releaseDocs = Join-Path $repoRoot 'docs/release/v3.2.9.2'
foreach ($doc in @('INSTALLATION.md', 'RELEASE_NOTES.md', 'COMPATIBILITY.md', 'KNOWN_ISSUES.md')) {
    $source = Join-Path $releaseDocs $doc
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $packageRoot $doc) -Force
    }
}
if (Test-Path -LiteralPath (Join-Path $repoRoot 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot 'LICENSE') -Destination (Join-Path $packageRoot 'LICENSE') -Force
}

foreach ($dir in @('data', 'logs')) {
    New-Item -ItemType Directory -Path (Join-Path $packageRoot $dir) -Force | Out-Null
}

$commit = (& git -C $repoRoot rev-parse --short HEAD 2>$null)
$versionText = @(
    "ScoutMind FM27 V$Version",
    "包名：$packageName-Windows-x64",
    "构建时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')",
    "构建提交：$commit",
    "前端：生产构建（vite build）",
    "后端：Python 3.11+（首次启动自动创建 backend/.venv）",
    "Native Reader：win-x64 自包含单文件",
    '说明：本包为 First Public Preview，只支持已验证的 FM27 构建。'
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $packageRoot 'VERSION.txt') -Value $versionText -Encoding UTF8

$readmeText = @(
    'ScoutMind FM27 — First Public Preview',
    '',
    '启动：在 PowerShell 7 中运行  .\scripts\Start-ScoutMind.ps1',
    '停止：.\scripts\Stop-ScoutMind.ps1',
    '诊断：.\scripts\Check-Environment.ps1',
    '备份：.\scripts\Backup-Database.ps1',
    '',
    '首次启动会自动创建 Python 虚拟环境并安装依赖（需要联网，约几分钟）。',
    '默认访问地址：http://127.0.0.1:8000',
    '详细说明见 INSTALLATION.md。'
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $packageRoot 'README.txt') -Value $readmeText -Encoding UTF8

# 5. ZIP + SHA256
Write-Step '生成 ZIP'
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -Path $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal

Write-Step '校验 ZIP 内容'
$verifyRoot = Join-Path $OutputRoot 'verify'
if (Test-Path -LiteralPath $verifyRoot) { Remove-Item -LiteralPath $verifyRoot -Recurse -Force }
Expand-Archive -LiteralPath $zipPath -DestinationPath $verifyRoot
$verifyPackage = Join-Path $verifyRoot $packageName
$requiredInZip = @(
    'backend/app/main.py',
    'backend/alembic.ini',
    'backend/requirements.txt',
    'frontend/dist/index.html',
    'live-reader/ScoutMind.LiveReader.exe',
    'live-reader/ScoutMind.Agent.exe',
    'live-reader/compatibility.json',
    'live-reader/scanner.sample.json',
    'scripts/Start-ScoutMind.ps1',
    'scripts/Stop-ScoutMind.ps1',
    'scripts/Check-Environment.ps1',
    'scripts/Backup-Database.ps1',
    'VERSION.txt',
    'README.txt'
)
foreach ($relative in $requiredInZip) {
    if (-not (Test-Path -LiteralPath (Join-Path $verifyPackage $relative))) {
        Fail "ZIP 缺少文件：$relative"
    }
}

$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$size = (Get-Item -LiteralPath $zipPath).Length
$sumFile = Join-Path $OutputRoot 'SHA256SUMS.txt'
Set-Content -LiteralPath $sumFile -Value ("{0}  {1}" -f $hash, (Split-Path -Leaf $zipPath)) -Encoding ASCII

Write-Host ''
Write-Host '[OK] 发布候选构建完成' -ForegroundColor Green
Write-Host "     ZIP：$zipPath"
Write-Host "     大小：$('{0:N0}' -f $size) 字节"
Write-Host "     SHA256：$hash"
Write-Host "     校验：$sumFile"
