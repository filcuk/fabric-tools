# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file release build with embedded onedir bootloader for setup install."""

from __future__ import annotations

import os
import sys
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
sys.path.insert(0, str(spec_dir))

from analysis_inputs import analysis_inputs  # noqa: E402

block_cipher = None
project_root = spec_dir.parent
src_root = project_root / "src"

datas, binaries, hiddenimports = analysis_inputs(project_root)

bootloader = os.environ.get("FABRIC_TOOLS_ONEDIR_BOOTLOADER", "").strip()
if not bootloader:
    raise SystemExit(
        "FABRIC_TOOLS_ONEDIR_BOOTLOADER must point at the onedir fabric-tools.exe "
        "(run scripts/build_exe.ps1, which builds onedir first)."
    )
bootloader_path = Path(bootloader)
if not bootloader_path.is_file():
    raise SystemExit(f"Onedir bootloader not found: {bootloader_path}")

# Extracted under sys._MEIPASS/_onedir_bootloader/fabric-tools.exe for setup install.
datas += [(str(bootloader_path), "_onedir_bootloader")]

a = Analysis(
    [str(src_root / "fabric_tools" / "__main__.py")],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "nbdime.tests",
        "nbformat.corpus.tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="fabric-tools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "res" / "app.ico"),
)
