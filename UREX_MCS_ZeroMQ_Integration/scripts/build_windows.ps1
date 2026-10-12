[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipProtoGeneration
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

function Invoke-Checked {
    param([Parameter(Mandatory=$true)][scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

Write-Host "[UREX] Installing build dependencies..."
Invoke-Checked { py -3 -m pip install -r requirements-build.txt }

if (-not $SkipProtoGeneration) {
    Write-Host "[UREX] Regenerating Protocol Buffer bindings..."
    Invoke-Checked { py -3 scripts/generate_protobuf.py }
}

if (-not $SkipTests) {
    Write-Host "[UREX] Running test suite..."
    Invoke-Checked { py -3 -m pytest -q }
}

Write-Host "[UREX] Building Windows release bundle..."
Invoke-Checked { py -3 -m PyInstaller --noconfirm --clean packaging/urex_mcs.spec }

$ExePath = Join-Path $ProjectRoot "dist\UREX_MCS_Simulator\UREX_MCS_Simulator.exe"
if (-not (Test-Path $ExePath)) {
    throw "Expected executable was not produced: $ExePath"
}

Write-Host "[UREX] Running packaged GUI smoke test (offscreen)..."
$oldQpa = $env:QT_QPA_PLATFORM
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    & $ExePath --smoke-test
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged smoke test failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:QT_QPA_PLATFORM = $oldQpa
}

Write-Host ""
Write-Host "Unsigned release bundle is ready:"
Write-Host "  $ExePath"
Write-Host ""
Write-Host "Before distribution, Authenticode-sign the EXE with:"
Write-Host "  .\scripts\sign_windows.ps1 -CertificateThumbprint <thumbprint>"
