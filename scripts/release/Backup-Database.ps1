#Requires -Version 7.0
<#
.SYNOPSIS
    备份 ScoutMind 的 SQLite 数据库（带时间戳，不覆盖已有备份）。

.DESCRIPTION
    使用 SQLite backup API 做一致性备份（WAL 模式下比直接复制文件安全），
    备份后校验文件大小与 PRAGMA integrity_check，并输出备份路径。
    不会删除或修改原数据库。

.PARAMETER Root
    发布包根目录；默认根据脚本位置推断。

.PARAMETER BackupsDir
    备份目录，默认 <Root>\backups。

.PARAMETER Database
    数据库文件路径，默认 <Root>\data\scoutmind.db。
#>
[CmdletBinding()]
param(
    [string]$Root,
    [string]$BackupsDir,
    [string]$Database
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
if (-not $BackupsDir) { $BackupsDir = Join-Path $root 'backups' }
if (-not $Database) { $Database = Join-Path $root 'data/scoutmind.db' }

if (-not (Test-Path -LiteralPath $Database)) {
    Write-Host "[FAIL] 数据库不存在：$Database" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $BackupsDir)) {
    New-Item -ItemType Directory -Path $BackupsDir -Force | Out-Null
}

# 优先使用发布包虚拟环境，其次系统 Python
$python = Join-Path $root 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    Write-Host '[FAIL] 未找到 Python，无法执行一致性备份。' -ForegroundColor Red
    exit 1
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$destination = Join-Path $BackupsDir "scoutmind-$stamp.db"
$suffix = 1
while (Test-Path -LiteralPath $destination) {
    $destination = Join-Path $BackupsDir ("scoutmind-$stamp-" + $suffix + '.db')
    $suffix++
}

$helper = Join-Path $PSScriptRoot 'backup_sqlite.py'
Write-Host "==> 备份 $Database" -ForegroundColor Cyan
& $python $helper --source $Database --destination $destination
if ($LASTEXITCODE -ne 0) {
    Write-Host '[FAIL] 备份失败，未产生可用文件。' -ForegroundColor Red
    exit 1
}

$file = Get-Item -LiteralPath $destination
Write-Host ''
Write-Host "[OK] 备份完成：$($file.FullName)" -ForegroundColor Green
Write-Host "     大小：$('{0:N0}' -f $file.Length) 字节"
Write-Host '     原数据库未被修改或删除。'
