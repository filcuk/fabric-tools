"""Shared Nuitka CLI flags for fabric-tools standalone / onefile builds."""

from __future__ import annotations

import sys
from pathlib import Path

EXE_NAME = "fabric-tools.exe"

# Packages that must be present at runtime (Nuitka may miss dynamic imports).
INCLUDE_PACKAGES = (
    "fabric_tools",
    "typer",
    "rich",
    "httpx",
    "httpcore",
    "anyio",
    "certifi",
    "azure",
    "azure.identity",
    "azure.identity.broker",
    "azure.core",
    "msal",
    "msal_extensions",
    "cryptography",
    "questionary",
    "prompt_toolkit",
    "nbdime",
    "nbformat",
    "jsonschema",
    "rfc3987_syntax",
    "lark",
)

INCLUDE_PACKAGE_DATA = (
    "certifi",
    "rfc3987_syntax",
    "jsonschema",
    "nbformat",
    "azure.identity",
    "msal",
    "cryptography",
)

NOFOLLOW_IMPORT_TO = (
    "*.tests",
    "*.test",
    "nbdime.tests",
    "nbformat.corpus.tests",
    "pytest",
    "_pytest",
)


def entry_script(project_root: Path) -> Path:
    return project_root / "packaging" / "nuitka_entry.py"


def windows_file_version(version: str | None = None) -> str:
    """Normalize a package version to a 4-part Windows file/product version."""
    if version is None:
        from fabric_tools import __version__ as version

    core = version.strip().split("+", 1)[0].split("-", 1)[0]
    parts: list[str] = []
    for segment in core.split("."):
        digits = "".join(ch for ch in segment if ch.isdigit())
        parts.append(digits or "0")
        if len(parts) == 4:
            break
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts)


def compiler_args(*, version_info: tuple[int, int] | None = None) -> list[str]:
    """C compiler flags for the current (or given) Python version.

    Nuitka rejects ``--mingw64`` on Python 3.13+; those builds need MSVC.
    """
    info = version_info if version_info is not None else sys.version_info[:2]
    if info >= (3, 13):
        return ["--msvc=latest"]
    return ["--mingw64"]


def shared_nuitka_args(
    project_root: Path,
    *,
    version_info: tuple[int, int] | None = None,
) -> list[str]:
    """Return Nuitka flags shared by standalone and onefile builds."""
    project_root = project_root.resolve()
    icon = project_root / "res" / "app.ico"
    win_version = windows_file_version()
    args: list[str] = [
        "--assume-yes-for-downloads",
        *compiler_args(version_info=version_info),
        "--windows-console-mode=force",
        f"--output-filename={EXE_NAME}",
        "--output-folder-name=fabric-tools",
        "--product-name=fabric-tools",
        "--company-name=fabric-tools",
        "--file-description=fabric-tools CLI",
        f"--file-version={win_version}",
        f"--product-version={win_version}",
    ]
    if icon.is_file():
        args.append(f"--windows-icon-from-ico={icon}")

    for package in INCLUDE_PACKAGES:
        args.append(f"--include-package={package}")
    for package in INCLUDE_PACKAGE_DATA:
        args.append(f"--include-package-data={package}")
    for pattern in NOFOLLOW_IMPORT_TO:
        args.append(f"--nofollow-import-to={pattern}")
    return args


def nuitka_command(
    project_root: Path,
    *,
    mode: str,
    output_dir: Path,
    version_info: tuple[int, int] | None = None,
) -> list[str]:
    """Full ``python -m nuitka …`` argument list (excluding the interpreter)."""
    if mode not in {"standalone", "onefile"}:
        raise ValueError(f"unsupported Nuitka mode: {mode!r}")
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    return [
        "-m",
        "nuitka",
        f"--mode={mode}",
        f"--output-dir={output_dir}",
        *shared_nuitka_args(project_root, version_info=version_info),
        str(entry_script(project_root)),
    ]
