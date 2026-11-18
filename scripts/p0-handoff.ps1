# P0 一键收集：把三个阶段要的东西打包成一个文件夹（或 zip），发给我即可
#
# 做四件事：
#   1. 真实数据审查（P0-1）：对最新的 FMSuperScout 导出跑 validate
#   2. 端到端验收（P0-6）：跑 acceptance-e2e
#   3. 读取器验收（P0-5）：跑 status/probe（读取器未发布时记录为 skipped）
#   4. 写一份 README 汇总，并把所有输出放进 exports\p0-report-<时间戳>\
#
# 用法：
#   .\scripts\p0-handoff.ps1
#   .\scripts\p0-handoff.ps1 -DumpPath 'C:\Users\you\AppData\Local\FMSuperScout\dump-1.json'
#   .\scripts\p0-handoff.ps1 -Zip                    # 额外打成一个 zip
param(
    [string]$DumpPath,
    [string]$DumpDir = (Join-Path $env:LOCALAPPDATA 'FMSuperScout'),
    [int]$SaveId = 0,
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [switch]$SkipReader,
    [switch]$Zip
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outDir = Join-Path $root "exports\p0-report-$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
}

function Invoke-Captured {
    <#  运行一条命令：输出同时写文件和屏幕；失败不抛，记录下来继续。 #>
    param([string]$File, [scriptblock]$Action)
    $path = Join-Path $outDir $File
    try {
        $output = & $Action *>&1
        $output | Out-File -FilePath $path -Encoding utf8
        foreach ($line in $output) { Write-Host $line }
        return $true
    }
    catch {
        $message = "ERROR: $($_.Exception.Message)"
        $message | Out-File -FilePath $path -Encoding utf8 -Append
        Write-Host $message -ForegroundColor Red
        return $false
    }
}

# ---------------------------------------------------------------- 0. 后端
Write-Section "0/4 检查后端"
$healthy = $false
try {
    $health = Invoke-RestMethod "$BaseUrl/api/v1/health" -TimeoutSec 5
    $healthy = $true
    Write-Host "后端已在运行：$BaseUrl（database=$($health.database)）"
}
catch {
    Write-Host "后端未运行，尝试启动……" -ForegroundColor Yellow
    $python = Join-Path $root 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        throw "找不到 $python。先在 backend 目录创建虚拟环境并安装依赖。"
    }
    Start-Process -FilePath $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend',
        '--host', '127.0.0.1', '--port', '8000' -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $outDir 'backend.log') `
        -RedirectStandardError (Join-Path $outDir 'backend.err.log')
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try { Invoke-RestMethod "$BaseUrl/api/v1/health" -TimeoutSec 3 | Out-Null; $healthy = $true; break } catch { }
    }
    if ($healthy) { Write-Host "后端已启动。" } else { Write-Host "后端启动失败，见 backend.err.log" -ForegroundColor Red }
}

# ---------------------------------------------------------------- 1. P0-1 审查
$dump = $null
if ($DumpPath) {
    if (-not (Test-Path $DumpPath)) { throw "找不到导出文件：$DumpPath" }
    $dump = Get-Item $DumpPath
}
elseif (Test-Path $DumpDir) {
    $dump = Get-ChildItem $DumpDir -Filter 'dump*.json' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
if ($null -eq $dump) {
    Write-Host "没有找到 FMSuperScout 导出（$DumpDir），跳过审查步骤。" -ForegroundColor Yellow
}
else {
    Write-Section "1/4 真实数据审查（P0-1）"
    $saveQuery = if ($SaveId -gt 0) { "?save_id=$SaveId" } else { "" }
    $reportPath = Join-Path $outDir 'fmscout-validate.json'
    $script = {
        param($Uri, $File, $Target)
        $report = Invoke-RestMethod -Method Post -Uri $Uri -InFile $File -ContentType 'application/json'
        $report | ConvertTo-Json -Depth 8 | Out-File -FilePath $Target -Encoding utf8
        foreach ($section in $report.sections) {
            Write-Output $section.title
            foreach ($row in $section.rows) {
                $value = if ($row.value -is [datetime]) { $row.value.ToString('s') } else { $row.value }
                Write-Output ("    {0,-24} {1}" -f $row.label, $value)
            }
        }
        Write-Output ("结论：{0} · 可否导入：{1}" -f $report.verdict.status, $report.verdict.ready_to_import)
    }
    Invoke-Captured -File 'fmscout-validate.txt' -Action { & $script "$BaseUrl/api/v1/imports/fmscout/validate$saveQuery" $dump.FullName $reportPath } | Out-Null
    Copy-Item $dump.FullName (Join-Path $outDir 'dump-raw.json') -Force
    Write-Host "原始导出已复制（如含个人信息请勿外发）：dump-raw.json"
}

# ---------------------------------------------------------------- 2. P0-6 E2E
Write-Section "2/4 端到端验收（P0-6）"
Invoke-Captured -File 'acceptance-e2e.txt' -Action {
    & (Join-Path $root 'scripts\acceptance-e2e.ps1') -BaseUrl $BaseUrl -SaveId $SaveId -OutDir $outDir
} | Out-Null

# ---------------------------------------------------------------- 3. P0-5 读取器
Write-Section "3/4 读取器验收（P0-5）"
$readerCandidates = @(
    (Join-Path $root 'publish\win-x64\ScoutMind.LiveReader.exe'),
    (Join-Path $root 'publish\ScoutMind.LiveReader.exe'),
    (Join-Path $root 'live-reader\publish\ScoutMind.LiveReader.exe')
)
$reader = $readerCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($SkipReader) {
    "已按参数跳过。" | Out-File (Join-Path $outDir 'acceptance-live-reader.txt') -Encoding utf8
    Write-Host "按参数跳过。"
}
elseif (-not $reader) {
    "读取器未发布（查找过：$($readerCandidates -join ' ; ')）`n发布命令：.\scripts\publish-windows.ps1" |
        Out-File (Join-Path $outDir 'acceptance-live-reader.txt') -Encoding utf8
    Write-Host "读取器未发布，已记录为 skipped。" -ForegroundColor Yellow
}
else {
    Invoke-Captured -File 'acceptance-live-reader.txt' -Action {
        & (Join-Path $root 'scripts\acceptance-live-reader.ps1') -OutDir $outDir
    }
}

# ---------------------------------------------------------------- 4. 汇总
Write-Section "4/4 汇总"
Get-ChildItem $outDir -File | ForEach-Object { Write-Host ("  {0,-32} {1,8:N0} bytes" -f $_.Name, $_.Length) }

$summary = @(
    "ScoutMind P0 handoff · $stamp",
    "base: $BaseUrl",
    "save: $SaveId",
    "dump: $(if ($dump) { $dump.FullName } else { '未找到' })",
    "backend healthy: $healthy",
    "",
    "文件说明：",
    "  fmscout-validate.txt/json  → P0-1 真实数据审查（发这个）",
    "  acceptance-e2e.txt         → P0-6 端到端结果（发这个）",
    "  acceptance-live-reader.txt → P0-5 status/probe 记录（发这个）",
    "  dump-raw.json              → 原始导出（可选；含个人信息时不要外发）",
    "",
    "把这些 txt/json 发我即可；dump 建议先用 scripts\register_fixture.py 登记，再只发样本文件。"
) -join "`n"
$summary | Out-File (Join-Path $outDir 'README.txt') -Encoding utf8
Write-Host $summary

if ($Zip) {
    $zipPath = "$outDir.zip"
    Compress-Archive -Path (Join-Path $outDir '*') -DestinationPath $zipPath -Force
    Write-Host "已打包：$zipPath" -ForegroundColor Green
}
Write-Host ""
Write-Host "目录：$outDir" -ForegroundColor Green
