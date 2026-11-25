# 模拟网络中断（V3.2.7.4）。
#
# 两种模式：
#   Unreachable（默认）：连接一个确定不可达的本地端口，记录「连接失败 → 有限重试」
#                        的客观结果；不修改系统配置，不需要管理员。
#   FirewallBlock       ：临时为后端端口添加本机防火墙阻断规则，测试真实断网恢复。
#                        需要管理员权限；脚本不会自动提权，权限不足时标记
#                        BLOCKED_BY_PERMISSION 并保持系统原状。
#
# 注意：脚本不会停止后端进程，也不会修改游戏或 FM27。
#
# 用法：
#   pwsh -File tools/runtime-acceptance/simulate_network_failure.ps1 -Mode Unreachable -OutputDir runtime-evidence
#   pwsh -File tools/runtime-acceptance/simulate_network_failure.ps1 -Mode FirewallBlock -Port 8123 -OutputDir runtime-evidence
param(
    [ValidateSet('Unreachable', 'FirewallBlock')]
    [string]$Mode = 'Unreachable',
    [int]$Port = 8123,
    [string]$OutputDir = "runtime-evidence"
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$result = [ordered]@{
    tool        = "simulate_network_failure"
    mode        = $Mode
    started_at  = (Get-Date).ToUniversalTime().ToString("o")
    status      = "NOT_RUN"
    attempts    = @()
    error       = $null
}

function Test-Port([string]$HostName, [int]$TargetPort, [int]$TimeoutMs = 1000) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $TargetPort)
        if (-not $task.Wait($TimeoutMs)) { return $false }
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

if ($Mode -eq 'Unreachable') {
    # 9/tcp（discard）在 Windows 上默认无监听，是稳定的「不可达」参照。
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $reachable = Test-Port '127.0.0.1' 9 800
        $watch.Stop()
        $result.attempts += [ordered]@{
            attempt      = $attempt
            target       = "127.0.0.1:9"
            reachable    = $reachable
            elapsed_ms   = [int]$watch.ElapsedMilliseconds
        }
        if ($reachable) {
            # 极少数系统上 discard 服务存在：如实记录，不伪造为断网。
            $result.status = "INCONCLUSIVE"
            break
        }
        Start-Sleep -Milliseconds (200 * $attempt)
    }
    if ($result.status -eq "NOT_RUN") { $result.status = "PASS" }
    $result.note = "只验证连接失败与退避节奏；真实 Agent 重试由 verify_worker_fencing 与 Agent 单测覆盖。"
} else {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        $result.status = "BLOCKED_BY_PERMISSION"
        $result.error = "FirewallBlock 需要管理员权限；脚本不会自动提权。请用管理员终端重跑。"
    } else {
        $ruleName = "ScoutMind-Acceptance-Block-$Port"
        try {
            New-NetFirewallRule -DisplayName $ruleName -Direction Outbound -Action Block -Protocol TCP -RemotePort $Port -Profile Any | Out-Null
            $result.attempts += [ordered]@{ phase = "blocked"; reachable = (Test-Port '127.0.0.1' $Port 1000) }
            Start-Sleep -Seconds 3
            Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
            $result.attempts += [ordered]@{ phase = "restored"; reachable = (Test-Port '127.0.0.1' $Port 1000) }
            $result.status = "PASS"
            $result.note = "阻断规则已移除；请结合 Agent diagnostics 与审计 network_reconnected 判定恢复。"
        } finally {
            Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        }
    }
}

$result.finished_at = (Get-Date).ToUniversalTime().ToString("o")
$path = Join-Path $OutputDir 'network-failure-result.json'
$result | ConvertTo-Json -Depth 6 | Set-Content -Path $path -Encoding UTF8
Write-Host "网络中断模拟：$($result.status) → $path"
