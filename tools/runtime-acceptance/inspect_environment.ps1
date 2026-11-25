# 采集运行环境事实（V3.2.7.4）。
#
# 只读取、不修改游戏或系统状态；不伪造 FM27 版本：
# 探测不到的东西一律写 null / "not_detected"，由人在真实验收时补充。
#
# 用法：
#   pwsh -File tools/runtime-acceptance/inspect_environment.ps1 [-OutputDir <目录>]
param(
    [string]$OutputDir = "runtime-evidence"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

function Get-CommandVersion([string]$Command) {
    try {
        $output = & $Command --version 2>$null
        if ($LASTEXITCODE -eq 0) { return ($output | Select-Object -First 1) }
    } catch { }
    return $null
}

$fmProcess = Get-Process -Name 'fm' -ErrorAction SilentlyContinue | Select-Object -First 1
$readerProcess = Get-Process -Name 'ScoutMind.LiveReader' -ErrorAction SilentlyContinue | Select-Object -First 1
$agentProcess = Get-Process -Name 'ScoutMind.Agent' -ErrorAction SilentlyContinue | Select-Object -First 1

$environment = [ordered]@{
    collected_at        = (Get-Date).ToUniversalTime().ToString("o")
    os                  = [ordered]@{
        platform   = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
        architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        powershell = $PSVersionTable.PSVersion.ToString()
    }
    tools               = [ordered]@{
        python  = Get-CommandVersion 'python'
        dotnet  = Get-CommandVersion 'dotnet'
        node    = Get-CommandVersion 'node'
        npm     = Get-CommandVersion 'npm'
    }
    fm27                = [ordered]@{
        process_detected   = [bool]$fmProcess
        process_id         = if ($fmProcess) { $fmProcess.Id } else { $null }
        version            = $null   # 由 Reader 的 --diagnostics 输出补充，本脚本不猜
        steam_build        = $null
        game_plugin_dll    = $null
        note               = "版本必须来自 Reader 诊断输出；未执行 Reader 时为 null"
    }
    scoutmind_processes = [ordered]@{
        reader_detected = [bool]$readerProcess
        agent_detected  = [bool]$agentProcess
    }
    repository          = [ordered]@{
        root    = $root
        branch  = (git -C $root rev-parse --abbrev-ref HEAD 2>$null)
        commit  = (git -C $root rev-parse HEAD 2>$null)
    }
    verdict             = if ($fmProcess) { "FM27_RUNNING_ENVIRONMENT_UNVERIFIED" } else { "REAL_FM27_UNAVAILABLE" }
}

$path = Join-Path $OutputDir 'environment.json'
$environment | ConvertTo-Json -Depth 8 | Set-Content -Path $path -Encoding UTF8
Write-Host "环境事实已写入：$path"
Write-Host "结论：$($environment.verdict)（真实游戏验收仍需人工执行）"
