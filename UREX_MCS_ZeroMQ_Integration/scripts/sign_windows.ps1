[CmdletBinding()]
param(
    [string]$FilePath,
    [string]$CertificateThumbprint,
    [string]$CertificateSubject,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$SignToolPath
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $FilePath) {
    $FilePath = Join-Path $ProjectRoot "dist\UREX_MCS_Simulator\UREX_MCS_Simulator.exe"
}
$FilePath = (Resolve-Path $FilePath).Path

if (-not $SignToolPath) {
    $sdkRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (-not (Test-Path $sdkRoot)) {
        throw "Windows SDK SignTool not found. Install the Windows SDK or pass -SignToolPath."
    }
    $candidate = Get-ChildItem $sdkRoot -Directory |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1
    if (-not $candidate) {
        throw "signtool.exe not found under $sdkRoot. Pass -SignToolPath explicitly."
    }
    $SignToolPath = $candidate
}

if ($CertificateThumbprint -and $CertificateSubject) {
    throw "Specify either -CertificateThumbprint or -CertificateSubject, not both."
}
if (-not $CertificateThumbprint -and -not $CertificateSubject) {
    throw "A signing identity is required. Pass -CertificateThumbprint (preferred) or -CertificateSubject."
}

$args = @(
    "sign",
    "/fd", "SHA256",
    "/tr", $TimestampUrl,
    "/td", "SHA256",
    "/d", "UREX MCS Simulator"
)

if ($CertificateThumbprint) {
    $normalized = ($CertificateThumbprint -replace "\s", "").ToUpperInvariant()
    $args += @("/sha1", $normalized)
} else {
    $args += @("/n", $CertificateSubject)
}
$args += $FilePath

Write-Host "[UREX] Signing: $FilePath"
& $SignToolPath @args
if ($LASTEXITCODE -ne 0) {
    throw "SignTool failed with exit code $LASTEXITCODE"
}

Write-Host "[UREX] Verifying Authenticode signature..."
& $SignToolPath verify /pa /all /v $FilePath
if ($LASTEXITCODE -ne 0) {
    throw "Signature verification failed with exit code $LASTEXITCODE"
}

$auth = Get-AuthenticodeSignature -FilePath $FilePath
if ($auth.Status -ne "Valid") {
    throw "PowerShell Authenticode verification returned: $($auth.Status) - $($auth.StatusMessage)"
}

Write-Host "[UREX] Signature valid. Publisher certificate:"
Write-Host "  $($auth.SignerCertificate.Subject)"
