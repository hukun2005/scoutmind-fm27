# FMSuperScout 导出 → ScoutMind 导入（适配层，幂等）
#
# 三种模式（对应产品规格 10.4）：
#   手动导入：.\scripts\import-fmscout.ps1                      # 自动找最新 dump 并导入
#             .\scripts\import-fmscout.ps1 -Path D:\dump\dump-1.json
#   先看映射：.\scripts\import-fmscout.ps1 -Preview              # 只输出字段映射报告，不写库
#   定时/实时：.\scripts\import-fmscout.ps1 -Watch               # 轮询 dump 目录，检测到新导出就导入
#
# 上游把 dump 写在 %LOCALAPPDATA%\FMSuperScout\（Mac 见上游文档），文件名以 dump 开头、.json 结尾。
# 只读取这些文件，绝不修改游戏、存档或 FMSuperScout 的文件。
param(
    [string]$Path,
    [string]$DumpDir = (Join-Path $env:LOCALAPPDATA 'FMSuperScout'),
    [int]$SaveId = 0,
    [string]$Token = $env:SCOUTMIND_API_TOKEN,
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [switch]$Preview,
    [switch]$Validate,
    [switch]$Watch,
    [int]$IntervalSeconds = 30
)
$ErrorActionPreference = 'Stop'

$headers = @{}
if ($Token) { $headers['X-ScoutMind-Token'] = $Token }

function Get-Query {
    if ($SaveId -gt 0) { "?save_id=$SaveId" } else { "" }
}

# 最新的 dump 文件：上游按修改时间写入同一个目录，文件名不一定递增。
function Find-LatestDump {
    param([string]$Directory)
    if (-not (Test-Path $Directory)) {
        throw "FMSuperScout 数据目录不存在：$Directory。请先运行 FMSuperScout 并在游戏内按 F9 导出。"
    }
    Get-ChildItem -Path $Directory -Filter 'dump*.json' -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Resolve-Dump {
    param([string]$ExplicitPath, [string]$Directory)
    if ($ExplicitPath) {
        if (-not (Test-Path $ExplicitPath)) { throw "文件不存在：$ExplicitPath" }
        return Get-Item $ExplicitPath
    }
    $latest = Find-LatestDump -Directory $Directory
    if ($null -eq $latest) { throw "在 $Directory 里没有找到 dump*.json，请在 FMSuperScout 里导出一次。" }
    return $latest
}

function Invoke-Preview {
    param([System.IO.FileInfo]$File)
    $uri = "$BaseUrl/api/v1/imports/fmscout/preview"
    Write-Host "预览映射：$($File.FullName) -> $uri"
    $response = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -InFile $File.FullName -ContentType 'application/json'
    $report = $response.report
    Write-Host ("球员 {0} / 跳过 {1} / 球队 {2} / 已映射属性 {3}" -f $report.players_converted, $report.players_skipped, $report.clubs_converted, $report.attributes_mapped)
    Write-Host ("已映射字段：" + ($report.mapped_fields -join ', '))
    Write-Host ("缺少字段（相关功能会显示「不可用」）：" + ($report.absent_fields -join ', '))
    if ($report.attributes_ignored.Count -gt 0) {
        Write-Host ("忽略属性：" + ($report.attributes_ignored -join ', '))
    }
    foreach ($warning in $report.warnings) { Write-Host "警告：$warning" }
    return $response
}

function Invoke-Import {
    param([System.IO.FileInfo]$File)
    $uri = "$BaseUrl/api/v1/imports/fmscout$(Get-Query)"
    Write-Host "导入：$($File.FullName) -> $uri"
    $response = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -InFile $File.FullName -ContentType 'application/json'
    $import = $response.import
    if ($import.duplicate) {
        Write-Host ("这份 dump 已经导入过（scan_id={0}），未写入新数据。" -f $import.scan_id)
    }
    else {
        Write-Host ("已导入：新建球员 {0}、更新 {1}、快照 {2}、拒绝 {3}" -f $import.players_created, $import.players_updated, $import.snapshots_created, $import.rows_rejected)
    }
    foreach ($warning in $response.report.warnings) { Write-Host "警告：$warning" }
    return $response
}

if ($Watch) {
    Write-Host "监听 $DumpDir，每 $IntervalSeconds 秒检查一次新的 dump（Ctrl+C 结束）。"
    $lastStamp = $null
    while ($true) {
        try {
            $file = Resolve-Dump -Directory $DumpDir
            $stamp = "$($file.FullName)|$($file.LastWriteTimeUtc.Ticks)"
            if ($stamp -ne $lastStamp) {
                Invoke-Import -File $file | Out-Null
                $lastStamp = $stamp
            }
        }
        catch {
            Write-Warning $_.Exception.Message
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
}

$dump = Resolve-Dump -ExplicitPath $Path -Directory $DumpDir
function Invoke-Validate {
    <#
      真实数据审查（P0-1）：打印 [1] File / [2] Dataset / [3] Field coverage / [4] Identity / [5] Risks。
      不写库；用于在导入真实导出之前判断字段是否齐全、版本是否在已验证范围。
    #>
    param([System.IO.FileInfo]$File)
    $uri = "$BaseUrl/api/v1/imports/fmscout/validate$(Get-Query)"
    Write-Host "真实数据审查：$($File.FullName)"
    Write-Host ("文件大小：{0:N0} bytes · SHA256：{1}" -f $File.Length, (Get-FileHash $File.FullName -Algorithm SHA256).Hash.ToLower())
    Write-Host ""
    $report = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -InFile $File.FullName -ContentType 'application/json'
    foreach ($section in $report.sections) {
        Write-Host $section.title
        foreach ($row in $section.rows) {
            $detail = if ($row.detail) { "  ($($row.detail))" } else { "" }
            $value = if ($row.value -is [datetime]) { $row.value.ToString('s') } else { $row.value }
            Write-Host ("    {0,-24} {1}{2}" -f $row.label, $value, $detail)
        }
        Write-Host ""
    }
    Write-Host ("结论：{0}" -f $report.verdict.status)
    if ($report.verdict.blockers.Count -gt 0) { Write-Host ("  阻塞项：" + ($report.verdict.blockers -join '；')) }
    if ($report.verdict.review.Count -gt 0) { Write-Host ("  需复核：" + ($report.verdict.review -join '；')) }
    Write-Host ("可否导入：{0}" -f $(if ($report.verdict.ready_to_import) { '可以（建议先记录此报告）' } else { '不可以，先处理阻塞项' }))
    return $report
}

if ($Validate) {
    Invoke-Validate -File $dump | Out-Null
    exit 0
}

if ($Preview) {
    Invoke-Preview -File $dump | ConvertTo-Json -Depth 6
}
else {
    Invoke-Import -File $dump | ConvertTo-Json -Depth 6
}
