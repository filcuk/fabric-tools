"""Shared PyInstaller Analysis inputs for fabric-tools onedir / onefile builds."""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules


def analysis_inputs(project_root: Path) -> tuple[list, list, list]:
    """Return (datas, binaries, hiddenimports) for the fabric-tools entrypoint."""
    datas: list = []
    binaries: list = []
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
        "fabric_tools.readonly",
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

    return datas, binaries, sorted(set(hiddenimports))
