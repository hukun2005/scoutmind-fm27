#Requires -Version 7.0
<#
.SYNOPSIS
    发布 ScoutMind 的 Windows 组件（实时读取器 + 桌面代理）。

.DESCRIPTION
    以自包含、单文件方式发布两个可执行程序到 publish/win-x64：
      * ScoutMind.LiveReader.exe  —— 读取器（检测、版本闸门、probe、扫描）
      * ScoutMind.Agent.exe       —— 桌面代理（调度扫描、同步后端）
    两个 exe 放在同一目录，代理默认把同目录的 ScoutMind.LiveReader.exe 当作读取器。
    随后把 compatibility.json 与 scanner.sample.json 复制到发布目录（scanner 配置仅在需要外部扫描器时使用）。

.PARAMETER Configuration
    生成配置，默认 Release。

.PARAMETER Runtime
    目标运行时标识符，默认 win-x64。

.PARAMETER OutputRoot
    自定义发布目录；默认 <仓库根目录>/publish/<Runtime>。

.PARAMETER SkipClean
    保留已有发布目录内容（默认会先清空）。

.EXAMPLE
    pwsh -File scripts/publish-windows.ps1

.EXAMPLE
    pwsh -File scripts/publish-windows.ps1 -OutputRoot D:\ScoutMind\bin -SkipClean
#>
[CmdletBinding()]
param(
    [string]$Configuration = 'Release',
    [string]$Runtime = 'win-x64',
    [string]$OutputRoot,
    [switch]$SkipClean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-DotNet {
    param([string[]]$Arguments)

    Write-Host "    dotnet $($Arguments -join ' ')" -ForegroundColor DarkGray
    & dotnet @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet $($Arguments[0]) 失败，退出码 $LASTEXITCODE。"
    }
}

$scriptsDirectory = $PSScriptRoot
$repoRoot = Split-Path -Parent $scriptsDirectory

if (-not (Test-Path -LiteralPath $repoRoot)) {
    throw "无法定位仓库根目录：$repoRoot"
}

$readerProject = Join-Path $repoRoot 'live-reader/ScoutMind.Reader/ScoutMind.Reader.csproj'
$agentProject = Join-Path $repoRoot 'desktop-agent/ScoutMind.Agent/ScoutMind.Agent.csproj'
$compatibilityFile = Join-Path $repoRoot 'config/compatibility.json'
$scannerSampleFile = Join-Path $repoRoot 'config/scanner.sample.json'

foreach ($path in @($readerProject, $agentProject, $compatibilityFile, $scannerSampleFile)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "缺少发布所需的文件：$path"
    }
}

$publishRoot = if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    Join-Path $repoRoot "publish/$Runtime"
} else {
    [System.IO.Path]::GetFullPath($OutputRoot)
}

Write-Step "发布目录：$publishRoot"
Write-Step "配置：$Configuration，运行时：$Runtime，自包含单文件"

if ((-not $SkipClean) -and (Test-Path -LiteralPath $publishRoot)) {
    Write-Step '清理旧的发布输出'
    Remove-Item -LiteralPath $publishRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $publishRoot -Force | Out-Null

$publishArguments = @(
    'publish', $readerProject,
    '-c', $Configuration,
    '-r', $Runtime,
    '--self-contained', 'true',
    '-p:PublishSingleFile=true',
    '-p:EnableCompressionInSingleFile=true',
    '-p:DebugType=None',
    '--nologo',
    '-o', $publishRoot
)

Write-Step '发布读取器 ScoutMind.LiveReader.exe'
Invoke-DotNet -Arguments $publishArguments

$agentPublishArguments = @(
    'publish', $agentProject,
    '-c', $Configuration,
    '-r', $Runtime,
    '--self-contained', 'true',
    '-p:PublishSingleFile=true',
    '-p:EnableCompressionInSingleFile=true',
    '-p:DebugType=None',
    '--nologo',
    '-o', $publishRoot
)

Write-Step '发布桌面代理 ScoutMind.Agent.exe'
Invoke-DotNet -Arguments $agentPublishArguments

Write-Step '复制兼容清单与扫描器示例配置'
Copy-Item -LiteralPath $compatibilityFile -Destination (Join-Path $publishRoot 'compatibility.json') -Force
Copy-Item -LiteralPath $scannerSampleFile -Destination (Join-Path $publishRoot 'scanner.sample.json') -Force

$readerExe = Join-Path $publishRoot 'ScoutMind.LiveReader.exe'
$agentExe = Join-Path $publishRoot 'ScoutMind.Agent.exe'
foreach ($exe in @($readerExe, $agentExe)) {
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "发布结果缺少可执行文件：$exe"
    }
}

Write-Step '发布完成'
Get-ChildItem -LiteralPath $publishRoot | Sort-Object Name | Format-Table Name, Length -AutoSize

Write-Host ''
Write-Host '后续步骤：' -ForegroundColor Green
Write-Host '  1. 运行发布目录中的 ScoutMind.LiveReader.exe status 检查检测与版本闸门结果。'
Write-Host '  2. 直接运行 ScoutMind.LiveReader.exe scan 即可：默认使用内置只读引擎（ScoutMind.FMReader），不需要外部扫描器。'
Write-Host '  3. 只有 compatibility.json 中状态为 verified 的构建才允许读取；candidate 条目会被拒绝。'
Write-Host '  4. 如需同步后端，在 ScoutMind.Agent.exe 同目录创建 agent.json 或设置 SCOUTMIND_API_TOKEN。'
Write-Host '  5. 启动游戏后运行 ScoutMind.Agent.exe scan --sync，或使用 watch --interval-minutes 定时扫描。'
Write-Host ''
