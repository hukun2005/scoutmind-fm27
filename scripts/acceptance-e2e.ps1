# P0-6 端到端验收
#
# 目标：从“真实数据已经导入”一路验到 ScoutMind 的页面与分析结果，而不是只看导入接口返回 201。
#
# 用法：
#   .\scripts\acceptance-e2e.ps1                      # 对当前存档跑全部检查
#   .\scripts\acceptance-e2e.ps1 -SaveId 2 -BaseUrl http://127.0.0.1:8000
#   .\scripts\acceptance-e2e.ps1 -RequireRealData     # 没有真实数据时判为失败（默认只警告）
param(
    [int]$SaveId = 0,
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [string]$Token = $env:SCOUTMIND_API_TOKEN,
    [switch]$RequireRealData,
    [string]$OutDir = '.\docs\acceptance'
)
$ErrorActionPreference = 'Stop'

$headers = @{}
if ($Token) { $headers['X-ScoutMind-Token'] = $Token }
$query = if ($SaveId -gt 0) { "?save_id=$SaveId" } else { "" }

$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param([string]$Name, [string]$Status, [string]$Detail)
    $checks.Add([pscustomobject]@{ Name = $Name; Status = $Status; Detail = $Detail })
}

function Get-Json {
    param([string]$Path, [string]$Label)
    try {
        return Invoke-RestMethod -Uri "$BaseUrl$Path" -Headers $headers -TimeoutSec 60
    }
    catch {
        Add-Check -Name $Label -Status 'FAIL' -Detail $_.Exception.Message
        return $null
    }
}

# 1. 服务与存档
$health = Get-Json '/api/v1/health' 'health'
if ($health) { Add-Check 'health' 'PASS' ("version {0} database {1}" -f $health.version, $health.database) }
$meta = Get-Json '/api/v1/meta/bootstrap' 'bootstrap'
if ($meta) {
    $hasReal = ($meta.data_sources | Where-Object { $_.source -ne 'synthetic_fixture' } | Measure-Object).Count -gt 0
    $status = if ($hasReal) { 'PASS' } elseif ($RequireRealData) { 'FAIL' } else { 'WARN' }
    Add-Check '数据来源' $status ("sources: " + (($meta.data_sources | ForEach-Object { "$($_.source)=$($_.records)" }) -join ', '))
}

# 2. 导入历史
$imports = Get-Json "/api/v1/imports$query" 'imports'
if ($imports) {
    $ok = ($imports.items | Where-Object { $_.status -in @('succeeded', 'partial') } | Measure-Object).Count
    Add-Check '导入成功记录' $(if ($ok -gt 0) { 'PASS' } else { 'FAIL' }) ("{0} 条 succeed/partial，最近状态 {1}" -f $ok, ($imports.items[0].status))
}

# 3. 覆盖度
$overview = Get-Json "/api/v1/analytics/overview$query" 'overview'
if ($overview) {
    $ca = $overview.coverage.ca
    Add-Check 'CA 覆盖' $(if ($ca -ge 0.6) { 'PASS' } elseif ($ca -gt 0) { 'WARN' } else { 'FAIL' }) ("ca={0:P0}" -f [double]$ca)
}

# 4. 分析模块
$squad = Get-Json "/api/v1/squad/overview$query" 'squad'
if ($squad) {
    Add-Check '阵容评分' $(if ($null -ne $squad.score) { 'PASS' } else { 'WARN' }) ("score={0} size={1}" -f $squad.score, $squad.squad_size)
}
$board = Get-Json "/api/v1/performance/board?limit=5$($(if ($SaveId -gt 0) { "&save_id=$SaveId" }))" 'performance'
if ($board) {
    Add-Check '表现分析' $(if ($board.total -gt 0) { 'PASS' } else { 'WARN' }) ("rows={0}（0 表示没有统计字段）" -f $board.total)
}
$recruit = Get-Json '/api/v1/recruitment/model' 'recruitment'
if ($recruit) { Add-Check '球探引擎模型' 'PASS' ("templates={0}" -f ($recruit.position_templates | Measure-Object).Count) }

# 5. 交易与候选
$categories = Get-Json '/api/v1/transfers/categories' 'transfers'
if ($categories) { Add-Check '交易类型体系' 'PASS' ("categories={0}" -f ($categories.categories | Measure-Object).Count) }
$candidates = Get-Json '/api/v1/transfers/candidates?status=all' 'candidates'
if ($candidates) { Add-Check '候选事件' 'PASS' ("total={0}" -f $candidates.total) }

# 6. AI 工具
$conversation = $null
try {
    $conversation = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/agent/conversations" -Headers $headers -ContentType 'application/json' -Body '{"title":"acceptance"}'
}
catch { Add-Check 'AI 会话' 'FAIL' $_.Exception.Message }
if ($conversation) {
    Add-Check 'AI 会话' 'PASS' ("conversation={0}" -f $conversation.id)
}

$passed = ($checks | Where-Object { $_.Status -eq 'PASS' } | Measure-Object).Count
$warned = ($checks | Where-Object { $_.Status -eq 'WARN' } | Measure-Object).Count
$failed = ($checks | Where-Object { $_.Status -eq 'FAIL' } | Measure-Object).Count

Write-Host ""
$checks | Format-Table -AutoSize
Write-Host ("PASS {0} · WARN {1} · FAIL {2}" -f $passed, $warned, $failed)
Write-Host "提示：WARN 多半意味着数据源没有这些字段（统计/伤病），不是代码缺陷；FAIL 才需要修。"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$log = Join-Path $OutDir ("e2e-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$lines = @("ScoutMind E2E acceptance", "time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')", "base: $BaseUrl", "save: $SaveId", "")
$lines += ($checks | ForEach-Object { "{0,-16} {1,-5} {2}" -f $_.Name, $_.Status, $_.Detail })
$lines += @("", "PASS $passed / WARN $warned / FAIL $failed")
$lines | Out-File -FilePath $log -Encoding utf8
Write-Host "记录已写入 $log"
if ($failed -gt 0) { exit 1 }
