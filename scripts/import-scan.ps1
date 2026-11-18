# 导入一份扫描报文到本地后端（幂等：同一 scan_id 只导入一次）
# 用法：.\scripts\import-scan.ps1 -Path .\exports\scan-xxxx.json [-SaveId 1] [-Token xxx] [-BaseUrl http://127.0.0.1:8000]
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [int]$SaveId = 0,
    [string]$Token = $env:SCOUTMIND_API_TOKEN,
    [string]$BaseUrl = 'http://127.0.0.1:8000'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Path)) { throw "文件不存在：$Path" }

$headers = @{}
if ($Token) { $headers['X-ScoutMind-Token'] = $Token }

$query = if ($SaveId -gt 0) { "?save_id=$SaveId" } else { "" }
$uri = "$BaseUrl/api/v1/imports/scan$query"

Write-Host "导入 $Path -> $uri"
$response = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -InFile $Path -ContentType 'application/json'
$response | ConvertTo-Json -Depth 6
