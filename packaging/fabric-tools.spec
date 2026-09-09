# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file console build for fabric-tools."""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None
# SPECPATH is the directory containing this .spec file (packaging/).
project_root = Path(SPECPATH).resolve().parent
src_root = project_root / "src"

datas = []
binaries = []
hiddenimports = [
    "fabric_tools",
    "fabric_tools.cli",
    "fabric_tools.auth",
    "fabric_tools.client",
    "fabric_tools.confirm",
    "fabric_tools.interactive",
    "fabric_tools.path_setup",
    "fabric_tools.console_ux",
    "fabric_tools.manifest",
    "fabric_tools.parsing",
    "fabric_tools.validate",
    "fabric_tools.exit_codes",
    "fabric_tools.notebook",
    "fabric_tools.notebook.definition",
    "fabric_tools.notebook.ops",
    "fabric_tools.notebook.compare",
    "typer",
    "rich",
    "httpx",
    "httpcore",
    "anyio",
    "certifi",
    "azure.identity",
    "azure.identity.broker",
    "azure.core",
    "msal",
    "msal_extensions",
    "questionary",
    "prompt_toolkit",
    "nbdime",
    "nbdime.diffing",
    "nbdime.diffing.notebooks",
    "nbdime.prettyprint",
    "nbformat",
    "jsonschema",
    "rfc3987_syntax",
    "lark",
]

# Prefer data/submodule collection over collect_all(nbdime) to avoid pulling tests.
for package in ("certifi", "rfc3987_syntax", "jsonschema", "nbformat"):
    datas += collect_data_files(package)
    hiddenimports += collect_submodules(package)

for package in ("azure.identity", "azure.identity.broker", "msal", "cryptography"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        datas += collect_data_files(package)

a = Analysis(
    [str(src_root / "fabric_tools" / "__main__.py")],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
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
    upx=True,
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
