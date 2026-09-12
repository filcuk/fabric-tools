"""Shared Nuitka CLI flags for fabric-tools standalone / onefile builds."""

from __future__ import annotations

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


def shared_nuitka_args(project_root: Path) -> list[str]:
    """Return Nuitka flags shared by standalone and onefile builds."""
    project_root = project_root.resolve()
    icon = project_root / "res" / "app.ico"
    args: list[str] = [
        "--assume-yes-for-downloads",
        "--mingw64",
        "--windows-console-mode=force",
        f"--output-filename={EXE_NAME}",
        "--product-name=fabric-tools",
        "--company-name=fabric-tools",
        "--file-description=fabric-tools CLI",
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
        *shared_nuitka_args(project_root),
        str(entry_script(project_root)),
    ]
