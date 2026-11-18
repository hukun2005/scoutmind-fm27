# P0-5 自研读取器验收记录
#
# 目标：把“能不能从正在运行的 FM27 读到真实数据”变成可复核的记录，而不是口头结论。
#
# 原则（产品规格 P0-5）：版本不匹配就返回 UnsupportedVersion 并拒绝扫描，不得为了让功能跑起来而强用旧偏移量。
#
# 用法：
#   .\scripts\acceptance-live-reader.ps1                     # status + probe，写记录
#   .\scripts\acceptance-live-reader.ps1 -IncludeScan        # probe 通过后额外尝试 scan
#   .\scripts\acceptance-live-reader.ps1 -Reader .\live-reader\publish\ScoutMind.LiveReader.exe
param(
    # 留空则按 publish\win-x64 → live-reader\publish → 仓库根目录 的顺序自动查找
    [string]$Reader,
    [string]$OutDir = ".\docs\acceptance",
    [switch]$IncludeScan,
    [string]$Out = ".\exports\scan-acceptance.json"
)
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Reader) {
    $candidates = @(
        (Join-Path $repoRoot 'publish\win-x64\ScoutMind.LiveReader.exe'),
        (Join-Path $repoRoot 'publish\ScoutMind.LiveReader.exe'),
        (Join-Path $repoRoot 'live-reader\publish\ScoutMind.LiveReader.exe'),
        (Join-Path $repoRoot 'ScoutMind.LiveReader.exe')
    )
    $Reader = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Reader -or -not (Test-Path $Reader)) {
    throw @"
找不到 ScoutMind.LiveReader.exe。先发布：
  .\scripts\publish-windows.ps1                 （自包含单文件，输出到 publish\win-x64）
或
  dotnet publish .\live-reader\ScoutMind.Reader -c Release -o .\publish\win-x64
"@
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $OutDir "live-reader-$stamp.txt"

function Invoke-Step {
    param([string]$Name, [string[]]$Arguments)
    Write-Host "== $Name ==" -ForegroundColor Cyan
    $output = & $Reader @Arguments 2>&1 | Out-String
    $code = $LASTEXITCODE
    Write-Host $output
    Write-Host ("退出码：{0}" -f $code)
    return @{ name = $Name; arguments = $Arguments; output = $output; exit = $code }
}

$results = @()
$results += Invoke-Step -Name 'status' -Arguments @('status')
$probe = Invoke-Step -Name 'probe' -Arguments @('probe')
$results += $probe

$probeOk = $probe.output -notmatch 'UnsupportedVersion' -and $probe.output -match '(?i)(verified|supported|ok)'
$scanState = 'skipped'
$scanOutput = ''
if ($IncludeScan) {
    if (-not $probeOk) {
        $scanState = 'blocked'
        $scanOutput = 'probe 未通过（版本不在已验证清单或无法读取内存），按规格拒绝扫描。'
        Write-Warning $scanOutput
    }
    else {
        New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
        $scan = Invoke-Step -Name 'scan' -Arguments @('scan', '--output', (Split-Path $Out -Parent))
        $results += $scan
        $scanState = if (Test-Path $Out) { "written:$Out" } else { 'no-output' }
        $scanOutput = $scan.output
    }
}

$header = @(
    "ScoutMind Live Reader acceptance",
    "time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')",
    "reader: $Reader",
    "host: $env:COMPUTERNAME",
    "probe_ok: $probeOk",
    "scan: $scanState",
    ""
) -join "`n"

$body = $header
foreach ($result in $results) {
    $body += "--- $($result.name) $(($result.arguments -join ' ')) (exit=$($result.exit)) ---`n$($result.output)`n"
}
if ($scanOutput) { $body += "--- scan summary ---`n$scanOutput`n" }

$body | Out-File -FilePath $log -Encoding utf8
Write-Host ""
Write-Host "记录已写入 $log"
Write-Host "下一步：把 status/probe 输出里的 App ID、Build ID、插件版本填到 docs/VERSION_COMPATIBILITY.md 与 docs/acceptance/CHECKLIST.md"
if ($probeOk -and $scanState -like 'written:*') {
    Write-Host "再执行：.\scripts\import-scan.ps1 -Path $Out  然后打开 ScoutMind 抽查球员/阵容/合同" -ForegroundColor Green
}
