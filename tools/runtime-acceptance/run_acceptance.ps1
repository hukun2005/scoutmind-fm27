# 一键运行 V3.2.7.4 运行期验收。
#
# 流程：环境检查 → 临时 SQLite + alembic upgrade head → 启动临时后端 →
#       存档隔离 / Worker 栅栏 / operation 幂等 → 网络中断模拟 →
#       证据汇总（脱敏清单）→ 停止后端。
#
# 安全：只监听 127.0.0.1，只使用临时数据库与临时数据目录；
#       真实 FM27 A/B 验收不在这里伪造成 PASS。
#
# 用法：
#   pwsh -File tools/runtime-acceptance/run_acceptance.ps1
#   pwsh -File tools/runtime-acceptance/run_acceptance.ps1 -Port 8123 -EvidenceDir docs/evidence/v3.2.7.4/runtime -KeepDatabase
param(
    [int]$Port = 8123,
    [string]$EvidenceDir = "docs/evidence/v3.2.7.4/runtime",
    [switch]$KeepDatabase
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$backend = Join-Path $root 'backend'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
$python = if (Test-Path $venvPython) { $venvPython } else { 'python' }

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$evidence = (Resolve-Path $EvidenceDir).Path
$temp = Join-Path $env:TEMP ("scoutmind-acceptance-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$dbPath = Join-Path $temp 'acceptance.db'
$dataDir = Join-Path $temp 'data'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$summary = [ordered]@{
    tool        = "run_acceptance"
    version     = "v3.2.7.4"
    started_at  = (Get-Date).ToUniversalTime().ToString("o")
    api         = "http://127.0.0.1:$Port/api/v1"
    database    = "<temp-sqlite>"
    steps       = @()
    real_fm27   = "REAL_FM27_ACCEPTANCE_PENDING"
    status      = "NOT_RUN"
}

function Add-Step([string]$Name, [string]$Status, [string]$Detail = "") {
    $script:summary.steps += [ordered]@{ name = $Name; status = $Status; detail = $Detail }
    Write-Host "[$Status] $Name $Detail"
}

$server = $null
try {
    # --- 环境检查 -------------------------------------------------------------------------------------
    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'inspect_environment.ps1') -OutputDir $evidence | Out-Host
    Add-Step 'inspect_environment' 'PASS'

    # --- 临时数据库 -----------------------------------------------------------------------------------
    $dbUrl = "sqlite:///" + ($dbPath -replace '\\', '/')
    $env:SCOUTMIND_DATABASE_URL = $dbUrl
    $env:SCOUTMIND_DATA_DIR = $dataDir
    Push-Location $backend
    try {
        & $python -m alembic upgrade head 2>&1 | Tee-Object -FilePath (Join-Path $evidence 'alembic-upgrade.log') | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head 失败（退出码 $LASTEXITCODE）" }
    } finally {
        Pop-Location
    }
    Add-Step 'alembic_upgrade' 'PASS' '临时 SQLite'

    # --- 启动临时后端 ---------------------------------------------------------------------------------
    $outLog = Join-Path $evidence 'backend-stdout.log'
    $errLog = Join-Path $evidence 'backend-stderr.log'
    $server = Start-Process -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--app-dir', $backend, '--host', '127.0.0.1', '--port', "$Port") `
        -PassThru -NoNewWindow -RedirectStandardOutput $outLog -RedirectStandardError $errLog

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch { }
        if ($server.HasExited) { break }
    }
    if (-not $ready) {
        Add-Step 'backend_start' 'FAIL' "后端未在 30s 内就绪；见 backend-stderr.log"
        throw "临时后端启动失败"
    }
    Add-Step 'backend_start' 'PASS' "pid=$($server.Id)"

    $api = "http://127.0.0.1:$Port/api/v1"

    # --- 三个验证器 -----------------------------------------------------------------------------------
    $verifiers = @(
        @{ Name = 'verify_save_isolation'; Args = @() },
        @{ Name = 'verify_worker_fencing'; Args = @('--database', $dbPath) },
        @{ Name = 'verify_operation_idempotency'; Args = @('--database', $dbPath) }
    )
    $failed = 0
    foreach ($verifier in $verifiers) {
        $script = Join-Path $PSScriptRoot ($verifier.Name + '.py')
        $arguments = @($script, '--api', $api, '--output', $evidence) + $verifier.Args
        & $python @arguments 2>&1 | Tee-Object -FilePath (Join-Path $evidence ($verifier.Name + '.log')) | Out-Host
        if ($LASTEXITCODE -eq 0) {
            Add-Step $verifier.Name 'PASS'
        } else {
            Add-Step $verifier.Name 'FAIL' "退出码 $LASTEXITCODE"
            $failed++
        }
    }

    # --- 网络中断模拟（无管理员权限时 Unreachable 模式仍可执行） ----------------------------------------
    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'simulate_network_failure.ps1') -Mode Unreachable -OutputDir $evidence | Out-Host
    if ($LASTEXITCODE -eq 0) { Add-Step 'simulate_network_failure' 'PASS' } else { Add-Step 'simulate_network_failure' 'FAIL' }

    # --- 真实 FM27 结论 -------------------------------------------------------------------------------
    # 自动化脚本不读取游戏、也不验证版本；无论检测到什么都只能标记待人工验收。
    $environment = Get-Content -Raw -Path (Join-Path $evidence 'environment.json') | ConvertFrom-Json
    $summary.real_fm27 = "REAL_FM27_ACCEPTANCE_PENDING"
    if ($environment.fm27.process_detected) {
        Add-Step 'real_fm27' 'NOT_RUN' "检测到名为 fm 的进程，但版本未验证；按 REAL_FM27_ACCEPTANCE_PENDING 处理"
    } else {
        Add-Step 'real_fm27' 'NOT_RUN' "未检测到 FM27；REAL_FM27_ACCEPTANCE_PENDING"
    }

    $summary.status = if ($failed -eq 0) { "PASS" } else { "FAIL" }
} catch {
    $summary.status = "FAIL"
    $summary.error = $_.Exception.Message
    Add-Step 'exception' 'FAIL' $_.Exception.Message
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
        Add-Step 'backend_stop' 'PASS'
    }
    Remove-Item Env:SCOUTMIND_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:SCOUTMIND_DATA_DIR -ErrorAction SilentlyContinue

    $summary.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $summary | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $evidence 'acceptance-run.json') -Encoding UTF8

    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'collect_evidence.ps1') -EvidenceDir $evidence | Out-Host

    if (-not $KeepDatabase) {
        Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
    } else {
        Write-Host "临时数据库保留：$temp"
    }
}

Write-Host ""
Write-Host "总体状态：$($summary.status)"
Write-Host "真实 FM27：$($summary.real_fm27)"
Write-Host "证据目录：$evidence"
if ($summary.status -eq 'FAIL') { exit 1 }
exit 0
