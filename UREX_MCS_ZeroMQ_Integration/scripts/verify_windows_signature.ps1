[CmdletBinding()]
param(
    [string]$FilePath
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $FilePath) {
    $FilePath = Join-Path $ProjectRoot "dist\UREX_MCS_Simulator\UREX_MCS_Simulator.exe"
}
$FilePath = (Resolve-Path $FilePath).Path

$sig = Get-AuthenticodeSignature -FilePath $FilePath
$sig | Format-List Status, StatusMessage, Path
if ($sig.SignerCertificate) {
    $sig.SignerCertificate | Format-List Subject, Issuer, Thumbprint, NotBefore, NotAfter
}
if ($sig.Status -ne "Valid") {
    exit 1
}
