#Requires -Version 7.0
<#
.SYNOPSIS
    诊断 ScoutMind 发布包运行环境，输出可读报告。

.DESCRIPTION
    检查 Windows、PowerShell、Python、.NET、目录、发布文件、端口、写权限、磁盘空间与数据库，
    以 PASS / WARN / FAIL 汇总；存在 FAIL 时退出码为 1。

.PARAMETER Root
    发布包根目录；默认根据脚本位置推断。

.PARAMETER Port
    需要检查的 API 端口，默认 8000。
#>
[CmdletBinding()]
param(
    [string]$Root,
    [int]$Port = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$results = [System.Collections.Generic.List[object]]::new()

function Add-Result {
    param([string]$Level, [string]$Name, [string]$Detail)
    $color = switch ($Level) { 'PASS' { 'Green' } 'WARN' { 'Yellow' } 'FAIL' { 'Red' } default { 'Gray' } }
    Write-Host ("[{0}] {1}：{2}" -f $Level, $Name, $Detail) -ForegroundColor $color
    $results.Add([pscustomobject]@{ Level = $Level; Name = $Name; Detail = $Detail })
}

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

Write-Host '=== ScoutMind 环境诊断 ===' -ForegroundColor Cyan

try {
    $root = Resolve-PackageRoot -Hint $Root
    Add-Result PASS '发布包目录' $root
} catch {
    Add-Result FAIL '发布包目录' $_.Exception.Message
    exit 1
}

# 系统
$os = Get-CimInstance Win32_OperatingSystem
if ($os.Caption -match 'Windows 1[01]') {
    Add-Result PASS 'Windows 版本' "$($os.Caption) $($os.Version)"
} else {
    Add-Result WARN 'Windows 版本' "$($os.Caption)（仅验证过 Windows 10/11）"
}
Add-Result PASS 'PowerShell' $PSVersionTable.PSVersion.ToString()

# Python
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $versionText = (& python --version 2>&1) -join ' '
    if ($versionText -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 11) {
        Add-Result PASS 'Python' "$versionText（$($python.Source)）"
    } else {
        Add-Result FAIL 'Python' "$versionText（需要 3.11+）"
    }
} else {
    Add-Result FAIL 'Python' '未找到 python，请安装 Python 3.11+ 并加入 PATH'
}

$venvPython = Join-Path $root 'backend/.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $venvPython) {
    Add-Result PASS '后端虚拟环境' $venvPython
} else {
    Add-Result WARN '后端虚拟环境' '尚未创建；首次运行 Start-ScoutMind.ps1 会自动安装'
}

# .NET（Optional：只有需要重新发布 Reader/Agent 才要求）
$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if ($dotnet) {
    $runtimes = (& dotnet --list-runtimes 2>&1) -join '; '
    Add-Result PASS '.NET Runtime' $runtimes
} else {
    Add-Result WARN '.NET Runtime' '未安装 dotnet（运行发布包不强制需要；仅重新发布 C# 组件时需要）'
}

# 关键文件
$required = @(
    'backend/app/main.py',
    'backend/alembic.ini',
    'backend/requirements.txt',
    'frontend/dist/index.html',
    'live-reader/ScoutMind.LiveReader.exe',
    'live-reader/ScoutMind.Agent.exe',
    'live-reader/compatibility.json',
    'live-reader/scanner.sample.json'
)
foreach ($relative in $required) {
    $path = Join-Path $root $relative
    if (Test-Path -LiteralPath $path) {
        Add-Result PASS "文件 $relative" (('{0:N0} 字节' -f (Get-Item -LiteralPath $path).Length))
    } else {
        Add-Result FAIL "文件 $relative" '缺失'
    }
}

# 目录与写权限
foreach ($relative in @('data', 'logs')) {
    $dir = Join-Path $root $relative
    try {
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $probe = Join-Path $dir ('.write-probe-' + [guid]::NewGuid().ToString('N') + '.tmp')
        Set-Content -LiteralPath $probe -Value 'ok'
        Remove-Item -LiteralPath $probe -Force
        Add-Result PASS "写入权限 $relative" $dir
    } catch {
        Add-Result FAIL "写入权限 $relative" $_.Exception.Message
    }
}

# 磁盘空间
$drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($root).TrimEnd('\').TrimEnd(':'))
$freeGb = [math]::Round($drive.Free / 1GB, 2)
if ($freeGb -ge 2) { Add-Result PASS '磁盘空间' "$freeGb GB 可用" } else { Add-Result WARN '磁盘空间' "$freeGb GB 可用（建议 2 GB 以上）" }

# 端口
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owner = ($listener | Select-Object -First 1).OwningProcess
    $name = (Get-Process -Id $owner -ErrorAction SilentlyContinue).ProcessName
    Add-Result WARN "端口 $Port" "已被占用（PID $owner / $name）；若为 ScoutMind 实例可直接访问"
} else {
    Add-Result PASS "端口 $Port" '空闲'
}

# 数据库
$database = Join-Path $root 'data/scoutmind.db'
if (Test-Path -LiteralPath $database) {
    Add-Result PASS '数据库' (('{0:N0} 字节：{1}' -f (Get-Item -LiteralPath $database).Length, $database))
} else {
    Add-Result WARN '数据库' '尚未初始化；首次启动时由 alembic 创建'
}

$failures = @($results | Where-Object { $_.Level -eq 'FAIL' }).Count
$warnings = @($results | Where-Object { $_.Level -eq 'WARN' }).Count
Write-Host ''
Write-Host ("汇总：PASS {0} / WARN {1} / FAIL {2}" -f ($results.Count - $failures - $warnings), $warnings, $failures) -ForegroundColor Cyan
if ($failures -gt 0) { exit 1 }
exit 0
