#requires -Version 5.1
<#
.SYNOPSIS
使用 PFX 证书对已生成的 Windows 安装包进行代码签名、校验并更新 SHA256SUMS。

.DESCRIPTION
优先调用 Windows SDK 的 signtool.exe（SHA256 + RFC3161 时间戳）。
适合给已经构建好的安装包补签名；重新构建时建议直接用 build-installer.ps1。

.EXAMPLE
.\scripts\sign-installer.ps1 `
  -Installer "C:\Users\hukun\Desktop\安装包\ScoutMind-FM27-Setup-x64.exe" `
  -CertificatePath "C:\secure\scoutmind-codesign.pfx"

.EXAMPLE
$env:CSC_KEY_PASSWORD = "证书密码"
.\scripts\sign-installer.ps1 -Installer .\release\ScoutMind-FM27-Setup-x64.exe -CertificatePath C:\secure\scoutmind.pfx
#>
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$CertificatePath,
    [string]$CertificatePassword = $env:CSC_KEY_PASSWORD,
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Installer)) { throw "安装包不存在：$Installer" }
if (-not (Test-Path $CertificatePath)) { throw "PFX 证书不存在：$CertificatePath" }
if (-not $CertificatePassword) {
    throw "缺少证书密码：请使用 -CertificatePassword 或环境变量 CSC_KEY_PASSWORD"
}

$installerPath = (Resolve-Path $Installer).Path
$pfxPath = (Resolve-Path $CertificatePath).Path

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path $kitsRoot) {
        $kits = Get-ChildItem $kitsRoot -Directory | Sort-Object Name -Descending
        foreach ($kit in $kits) {
            $candidate = Join-Path $kit.FullName "x64\signtool.exe"
            if (Test-Path $candidate) { return $candidate }
        }
    }
    return $null
}

$signtool = Find-SignTool
if (-not $signtool) {
    throw "未找到 signtool.exe。请安装 Windows SDK（含 Signing Tools），或改用 build-installer.ps1 让 electron-builder 调用签名。"
}

Write-Host "==> 签名：$installerPath" -ForegroundColor Cyan
& $signtool sign /fd SHA256 /f $pfxPath /p $CertificatePassword /tr $TimestampServer /td SHA256 $installerPath
if ($LASTEXITCODE -ne 0) { throw "signtool 签名失败，退出码 $LASTEXITCODE" }

$signature = Get-AuthenticodeSignature $installerPath
if ($signature.Status -ne "Valid") {
    throw "签名校验失败：$($signature.Status) - $($signature.StatusMessage)"
}

$hash = (Get-FileHash $installerPath -Algorithm SHA256).Hash.ToLower()
$fileName = Split-Path $installerPath -Leaf
"$hash  $fileName" | Set-Content (Join-Path (Split-Path $installerPath) "SHA256SUMS.txt") -Encoding ascii

Write-Host "==> 签名成功" -ForegroundColor Green
Write-Host "签名主体: $($signature.SignerCertificate.Subject)"
Write-Host "SHA256: $hash"
