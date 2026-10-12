# -*- mode: python ; coding: utf-8 -*-
"""Windows release bundle for the UREX MCS Simulator.

The release entry point is UREX_MCS_Simulator.exe.  The legacy .bat files remain
for source-tree development only and are not part of the release bundle.
"""

from pathlib import Path

project_root = Path(SPECPATH).resolve().parent.parent

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "scenarios" / "default.json"), "scenarios"),
        (str(project_root / "schema" / "urex.proto"), "schema"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UREX_MCS_Simulator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="UREX_MCS_Simulator",
)
