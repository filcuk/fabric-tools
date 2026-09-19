"""Invoke PowerShell + SqlServer (TOM) for semantic-model RLS role membership (spike).

Uses the checked-in ``scripts/xmla_role_members.ps1`` script. Requires Windows and the
SqlServer module from the PowerShell Gallery. The access token is passed on stdin
JSON only (never argv).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

SCRIPT_ENV = "FABRIC_TOOLS_XMLA_SCRIPT"
SQLSERVER_MODULE = "SqlServer"
INSTALL_HINT = "Install-Module SqlServer -Scope CurrentUser"

XmlaAction = Literal["list", "member_add", "member_remove"]


class XmlaRolesError(RuntimeError):
    """XMLA / PowerShell role-membership helper failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class XmlaRolesResult:
    """Parsed JSON response from the PowerShell script."""

    ok: bool
    changed: bool
    message: str
    roles: list[dict[str, Any]]
    code: str | None = None
    detail: str | None = None
    raw: dict[str, Any] | None = None


def workspace_xmla_connection(workspace_display_name: str) -> str:
    """Build the Power BI XMLA data-source URI for a workspace display name."""
    encoded = quote(workspace_display_name, safe="")
    return f"powerbi://api.powerbi.com/v1.0/myorg/{encoded}"


def resolve_script_path() -> Path:
    """Locate ``xmla_role_members.ps1`` (env override, then repo ``scripts/``)."""
    override = os.environ.get(SCRIPT_ENV)
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path.resolve()
        raise XmlaRolesError(
            f"{SCRIPT_ENV} points to missing script: {path}",
            code="script_missing",
        )

    here = Path(__file__).resolve()
    candidates = [
        here.parents[2]
        / "scripts"
        / "xmla_role_members.ps1",  # src/fabric_tools → repo
        Path.cwd() / "scripts" / "xmla_role_members.ps1",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise XmlaRolesError(
        "xmla_role_members.ps1 not found. Set "
        f"{SCRIPT_ENV} or run from a fabric-tools checkout.",
        code="script_missing",
    )


def find_powershell() -> str:
    """Prefer ``pwsh``, else Windows PowerShell 5.1."""
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    raise XmlaRolesError(
        "Neither pwsh nor powershell found on PATH (Windows required).",
        code="powershell_missing",
    )


def _ps_run(
    script_block: str,
    *,
    powershell: str | None = None,
) -> subprocess.CompletedProcess[str]:
    exe = powershell or find_powershell()
    return subprocess.run(  # noqa: S603
        [
            exe,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script_block,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def sqlserver_module_available(*, powershell: str | None = None) -> bool:
    """Return True if SqlServer is listed by ``Get-Module -ListAvailable``."""
    # Avoid PowerShell string injection: module name is a constant.
    block = (
        f"if (Get-Module -ListAvailable -Name {SQLSERVER_MODULE}) "
        "{ exit 0 } else { exit 1 }"
    )
    result = _ps_run(block, powershell=powershell)
    return result.returncode == 0


def install_sqlserver_module(*, powershell: str | None = None) -> None:
    """Install SqlServer from PSGallery for the current user."""
    block = (
        f"Install-Module -Name {SQLSERVER_MODULE} -Scope CurrentUser "
        "-Repository PSGallery -Force -AllowClobber"
    )
    result = _ps_run(block, powershell=powershell)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip() or "unknown error"
        raise XmlaRolesError(
            f"Failed to install {SQLSERVER_MODULE}: {err}",
            code="install_failed",
            detail=err,
        )
    if not sqlserver_module_available(powershell=powershell):
        raise XmlaRolesError(
            f"{SQLSERVER_MODULE} still not available after Install-Module.",
            code="install_failed",
        )


def ensure_sqlserver_module(
    *,
    offer_install: bool = True,
    silent: bool = False,
    confirm: Any | None = None,
    powershell: str | None = None,
) -> None:
    """Ensure SqlServer is installed; optionally offer a confirmed Gallery install.

    *confirm* is a callable ``(message: str) -> bool`` (defaults to ``typer.confirm``).
    When *silent* is True, never prompt — raise with the install hint instead.
    """
    if sqlserver_module_available(powershell=powershell):
        return

    hint = (
        f"{SQLSERVER_MODULE} PowerShell module not found. Install with: {INSTALL_HINT}"
    )
    if silent or not offer_install:
        raise XmlaRolesError(hint, code="module_missing")

    if confirm is None:
        import typer

        confirm = typer.confirm

    prompt = (
        f"{SQLSERVER_MODULE} PowerShell module not found. "
        f"Install from PSGallery for CurrentUser now?"
    )
    if not confirm(prompt, default=False):
        raise XmlaRolesError(
            f"Aborted. To install later, run: {INSTALL_HINT}",
            code="module_missing",
        )
    install_sqlserver_module(powershell=powershell)


def _parse_response(stdout: str, stderr: str, returncode: int) -> XmlaRolesResult:
    text = (stdout or "").strip()
    if not text:
        err = (stderr or "").strip() or f"PowerShell exited {returncode} with no stdout"
        raise XmlaRolesError(err, code="empty_response", detail=stderr or None)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise XmlaRolesError(
            f"Invalid JSON from xmla_role_members.ps1: {exc}",
            code="invalid_json",
            detail=text[:800],
        ) from exc

    if not isinstance(data, dict):
        raise XmlaRolesError(
            "Unexpected JSON root from xmla_role_members.ps1",
            code="invalid_json",
            detail=text[:800],
        )

    ok = bool(data.get("ok"))
    roles = data.get("roles")
    if roles is None:
        roles_list: list[dict[str, Any]] = []
    elif isinstance(roles, list):
        roles_list = [r for r in roles if isinstance(r, dict)]
    else:
        roles_list = []

    result = XmlaRolesResult(
        ok=ok,
        changed=bool(data.get("changed")),
        message=str(data.get("message") or ""),
        roles=roles_list,
        code=str(data["code"]) if data.get("code") is not None else None,
        detail=str(data["detail"]) if data.get("detail") is not None else None,
        raw=data,
    )
    if not ok:
        raise XmlaRolesError(
            result.message or "XMLA role operation failed",
            code=result.code,
            detail=result.detail,
        )
    return result


def invoke_xmla_roles(
    *,
    action: XmlaAction,
    workspace_name: str,
    database_name: str,
    access_token: str,
    role_name: str | None = None,
    member_name: str | None = None,
    member_id: str | None = None,
    identity_provider: str = "AzureAD",
    member_type: str = "Auto",
    offer_install: bool = True,
    silent: bool = False,
    confirm: Any | None = None,
    powershell: str | None = None,
    script_path: Path | None = None,
) -> XmlaRolesResult:
    """Run list / member_add / member_remove via the PowerShell TOM script."""
    if sys.platform != "win32":
        raise XmlaRolesError(
            "XMLA role membership requires Windows PowerShell.",
            code="unsupported_platform",
        )

    ensure_sqlserver_module(
        offer_install=offer_install,
        silent=silent,
        confirm=confirm,
        powershell=powershell,
    )

    script = script_path or resolve_script_path()
    exe = powershell or find_powershell()

    payload: dict[str, Any] = {
        "action": action,
        "workspaceName": workspace_name,
        "databaseName": database_name,
        "accessToken": access_token,
    }
    if role_name is not None:
        payload["roleName"] = role_name
    if member_name is not None:
        payload["member"] = {
            "memberName": member_name,
            "memberId": member_id,
            "identityProvider": identity_provider,
            "memberType": member_type,
        }

    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW

    proc = subprocess.run(  # noqa: S603
        [
            exe,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    return _parse_response(proc.stdout, proc.stderr, proc.returncode)
