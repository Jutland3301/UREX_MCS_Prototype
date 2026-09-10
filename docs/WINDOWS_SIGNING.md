# Windows release signing

## Goal

The distributed entry point is `UREX_MCS_Simulator.exe`, not `run.bat` or
`setup_and_run.bat`. The BAT files are retained only for developers who run the
source tree directly.

This matters because BAT files are not a suitable Authenticode application
release surface. Windows application trust should be attached to a PE executable
(or an installer/package) that can carry a verifiable publisher signature.

## Build

On a Windows x64 development machine with Python 3 and the Windows SDK:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

This performs the following:

1. installs build dependencies;
2. regenerates the Python Protocol Buffer binding;
3. runs the tests;
4. builds `dist\UREX_MCS_Simulator\UREX_MCS_Simulator.exe` with PyInstaller;
5. starts the frozen GUI once in offscreen smoke-test mode and exits.

The output at this point is **unsigned** and should not be distributed.

## Sign

Install/access the team's public code-signing certificate so that Windows can
see it in the current user's certificate store. This also works with certificate
providers whose private key is backed by a USB token/HSM, as long as the
provider exposes the certificate/private-key operation through Windows.

Find an eligible certificate:

```powershell
Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
  Format-Table Subject, Thumbprint, NotAfter
```

Then sign the final executable:

```powershell
.\scripts\sign_windows.ps1 -CertificateThumbprint "<THUMBPRINT>"
```

The script uses:

- SHA-256 file digest;
- an RFC 3161 timestamp;
- SHA-256 timestamp digest;
- `signtool verify /pa /all /v` after signing;
- `Get-AuthenticodeSignature` as a second verification.

Do not modify the executable after signing. Rebuild first, then sign again.

## Verification on another Windows machine

```powershell
.\scripts\verify_windows_signature.ps1 `
  -FilePath .\dist\UREX_MCS_Simulator\UREX_MCS_Simulator.exe
```

Explorer should also show the signature under:

`Properties -> Digital Signatures`

## Which certificate should UREX use?

For public/unmanaged Windows machines, use a publicly trusted OV code-signing
certificate or an approved signing service. Modern public code-signing private
keys are normally hardware/HSM backed; do not design the release pipeline
around committing a `.pfx` file or private key to the repository.

For NUS-managed lab machines only, an internal NUS PKI certificate can also be
appropriate if the NUS root/publisher trust is deployed to those machines. A
self-signed development certificate is useful for testing the mechanics but is
not equivalent to public trust and does not by itself remove SmartScreen
reputation warnings on arbitrary user PCs.

## SmartScreen caveat

A valid signature fixes the "unknown/unverified publisher" part of the problem
and allows publisher reputation to accumulate, but a brand-new signed binary
can still receive a Microsoft Defender SmartScreen "unrecognized app" warning
until reputation exists. Signing every release with the same publisher identity
is therefore important.

If zero SmartScreen download warnings is a hard requirement for unmanaged
consumer PCs, Microsoft Store distribution is the most deterministic path.
