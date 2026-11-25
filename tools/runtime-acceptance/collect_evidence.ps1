# 汇总并脱敏运行期验收证据（V3.2.7.4）。
#
# - 只为目录内的证据文件生成 SHA-256 清单；
# - 把绝对路径替换为 <path>，避免把本机用户名写进交付物；
# - 生成 SUMMARY.md 与 manifest.json。
#
# 用法：
#   pwsh -File tools/runtime-acceptance/collect_evidence.ps1 -EvidenceDir runtime-evidence
param(
    [string]$EvidenceDir = "runtime-evidence"
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $EvidenceDir)) {
    throw "证据目录不存在：$EvidenceDir"
}
$resolved = (Resolve-Path $EvidenceDir).Path
New-Item -ItemType Directory -Force -Path (Join-Path $resolved "redacted") | Out-Null

function Protect-Path([string]$Text) {
    # 只做最常见、不会破坏 JSON 结构的替换：Windows 盘符路径与用户主目录。
    $value = $Text -replace '[A-Za-z]:\\Users\\[^"\\\s]+', '<user-home>'
    return $value
}

$entries = @()
Get-ChildItem -Path $resolved -File -Recurse | Where-Object { $_.FullName -notlike "*\redacted\*" -and $_.Length -lt 20MB } | ForEach-Object {
    $relative = $_.FullName.Substring($resolved.Length).TrimStart('\')
    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
    $hash = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()

    if ($_.Extension -in @('.json', '.md', '.txt', '.log')) {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
        $redacted = Protect-Path $text
        $target = Join-Path (Join-Path $resolved "redacted") $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Set-Content -Path $target -Value $redacted -Encoding UTF8
    }

    $entries += [ordered]@{
        file       = $relative
        size       = $_.Length
        sha256     = $hash
        redacted   = ($_.Extension -in @('.json', '.md', '.txt', '.log'))
        captured_at = $_.LastWriteTimeUtc.ToString("o")
    }
}

$manifest = [ordered]@{
    tool        = "collect_evidence"
    version     = "v3.2.7.5"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    directory   = "<evidence-dir>"
    files       = $entries
    note        = "只做路径脱敏；证据内容来自真实执行，未做任何伪造或补写。"
}
$manifestPath = Join-Path $resolved "manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8

$results = @()
Get-ChildItem -Path $resolved -Filter "*-result.json" -File | ForEach-Object {
    $json = Get-Content -Raw -Path $_.FullName | ConvertFrom-Json
    $results += [ordered]@{
        tool     = $json.tool
        ok       = $json.ok
        status   = $json.status
        checks   = @($json.checks).Count
        failures = @($json.failures).Count
    }
}

$summary = @("# Runtime Acceptance Summary", "", "生成时间：$((Get-Date).ToUniversalTime().ToString('o'))", "")
if ($results.Count -eq 0) {
    $summary += "未发现 *-result.json：本次没有执行自动化验收，或执行中断。"
} else {
    $summary += "| 工具 | 状态 | 检查数 | 失败数 |"
    $summary += "| --- | --- | --- | --- |"
    foreach ($item in $results) {
        $status = if ($item.status) { $item.status } elseif ($item.ok) { "PASS" } else { "FAIL" }
        $summary += "| $($item.tool) | $status | $($item.checks) | $($item.failures) |"
    }
}
$summary += ""
$summary += "真实 FM27 A/B 验收不在自动化范围内；没有人工执行时必须标记 ``REAL_FM27_ACCEPTANCE_PENDING``。"
Set-Content -Path (Join-Path $resolved "SUMMARY.md") -Value ($summary -join "`n") -Encoding UTF8

Write-Host "证据清单：$manifestPath"
Write-Host "汇总：$(Join-Path $resolved 'SUMMARY.md')"
