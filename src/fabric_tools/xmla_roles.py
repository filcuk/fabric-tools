"""Invoke PowerShell + SqlServer (TOM) for semantic-model RLS role membership.

Uses ``xmla_role_members.ps1`` (shipped beside this module; also under ``scripts/``).
Requires Windows and the SqlServer module from the PowerShell Gallery. The access
token is passed on stdin JSON only (never argv).
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

SCRIPT_ENV = "FABRIC_TOOLS_XMLA_SCRIPT"
TIMEOUT_ENV = "FABRIC_TOOLS_XMLA_TIMEOUT"
CONNECT_TIMEOUT_ENV = "FABRIC_TOOLS_XMLA_CONNECT_TIMEOUT"
SQLSERVER_MODULE = "SqlServer"
INSTALL_HINT = "Install-Module SqlServer -Scope CurrentUser"
DEFAULT_TIMEOUT_SECONDS = 25.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 15
INSTALL_TIMEOUT_SECONDS = 900.0
PROGRESS_PREFIX = "##fabric-tools## "
STAGE_ACTIONS: dict[str, str] = {
    "loading_module": "loading SqlServer module",
    "connecting": "connecting via XMLA",
    "loading_model": "loading model",
    "listing_roles": "listing roles",
    "adding_member": "adding role member",
    "removing_member": "removing role member",
    "saving": "saving model changes",
}


XmlaAction = Literal["list", "member_add", "member_remove"]
ProgressCallback = Callable[[str], None]


class XmlaRolesError(RuntimeError):
    """XMLA / PowerShell role-membership helper failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        detail: str | None = None,
        stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail
        self.stage = stage


@dataclass(frozen=True)
class XmlaRolesResult:
    """Parsed JSON response from the PowerShell script."""

    ok: bool
    changed: bool
    message: str
    roles: list[dict[str, Any]]
    code: str | None = None
    detail: str | None = None
    stage: str | None = None
    raw: dict[str, Any] | None = None


def stage_action(stage: str) -> str:
    """Map a PowerShell stage id to a spinner action phrase."""
    return STAGE_ACTIONS.get(stage, stage.replace("_", " "))


def is_personal_workspace(
    *,
    workspace_type: str | None = None,
    display_name: str | None = None,
) -> bool:
    """True for Fabric My workspace (type Personal or display name)."""
    if (workspace_type or "").casefold() == "personal":
        return True
    name = (display_name or "").strip().casefold()
    return name in {"my workspace", "myworkspace"}


def workspace_xmla_connection(
    workspace_display_name: str,
    *,
    workspace_type: str | None = None,
    tenant_id: str | None = None,
    owner_upn_or_oid: str | None = None,
) -> str:
    """Build the Power BI XMLA data-source URI for a workspace.

    Shared (capacity) workspaces use ``v1.0/myorg/{name}``.
    Personal workspaces (My workspace) require the v2 form::

        powerbi://api.powerbi.com/v2.0/{tenantId}/home/myworkspace/{UPN|oid}

    Using the v1 ``…/myorg/My workspace`` URL hangs in client libraries instead
    of failing fast — callers must pass personal workspace identity plus
    token-derived *tenant_id* and *owner_upn_or_oid*.
    """
    if is_personal_workspace(
        workspace_type=workspace_type, display_name=workspace_display_name
    ):
        if not tenant_id or not owner_upn_or_oid:
            raise XmlaRolesError(
                "Personal workspace (My workspace) XMLA requires tenant id and "
                "owner UPN or object id from the signed-in token. The workspace "
                "must also be on Premium / PPU / Fabric capacity with XMLA "
                "read/write enabled.",
                code="personal_workspace_xmla",
            )
        owner = quote(str(owner_upn_or_oid).strip(), safe="")
        return (
            f"powerbi://api.powerbi.com/v2.0/{tenant_id.strip()}"
            f"/home/myworkspace/{owner}"
        )

    encoded = "/".join(
        quote(segment, safe="") for segment in workspace_display_name.split("/")
    )
    return f"powerbi://api.powerbi.com/v1.0/myorg/{encoded}"


def access_token_claims(access_token: str) -> dict[str, Any]:
    """Decode a JWT access-token payload (no signature verification)."""
    import base64

    parts = access_token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def ensure_workspace_supports_xmla(workspace: dict[str, Any]) -> None:
    """Raise if *workspace* cannot use the Power BI XMLA endpoint.

    XMLA requires a Premium / PPU / Fabric capacity. Personal (My) workspace and
    shared workspaces without ``capacityId`` fail later with opaque AMO errors
    (``Authentication failed for all authenticators``); check up front.
    """
    capacity_id = workspace.get("capacityId")
    if isinstance(capacity_id, str) and capacity_id.strip():
        return

    raw_name = workspace.get("displayName") or workspace.get("name") or "workspace"
    name = str(raw_name)
    ws_type = workspace.get("type")
    type_str = ws_type if isinstance(ws_type, str) else None
    if is_personal_workspace(workspace_type=type_str, display_name=name):
        raise XmlaRolesError(
            f"Personal workspace '{name}' is not assigned to a Premium / PPU / "
            "Fabric capacity (capacityId is empty). XMLA role membership requires "
            "a capacity with XMLA read/write enabled. Assign a capacity in "
            "workspace settings, or target a capacity-backed shared workspace.",
            code="xmla_capacity_required",
        )
    raise XmlaRolesError(
        f"Workspace '{name}' has no capacityId; XMLA is only available on "
        "Premium / PPU / Fabric capacities with XMLA read/write enabled.",
        code="xmla_capacity_required",
    )


def personal_workspace_owner_from_token(access_token: str) -> tuple[str, str]:
    """Return ``(tenant_id, upn_or_oid)`` for personal-workspace XMLA v2 URLs.

    Prefers object id (stable) then UPN / preferred_username.
    """
    claims = access_token_claims(access_token)
    tenant_id = claims.get("tid")
    owner = (
        claims.get("oid")
        or claims.get("upn")
        or claims.get("preferred_username")
        or claims.get("unique_name")
    )
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise XmlaRolesError(
            "Access token has no tenant id (tid); cannot build My workspace XMLA URL.",
            code="personal_workspace_xmla",
        )
    if not isinstance(owner, str) or not owner.strip():
        raise XmlaRolesError(
            "Access token has no UPN/object id; cannot build My workspace XMLA URL.",
            code="personal_workspace_xmla",
        )
    return tenant_id.strip(), owner.strip()


def resolve_script_path() -> Path:
    """Locate ``xmla_role_members.ps1`` (env, package sibling, then repo ``scripts/``)."""
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
        here.with_name("xmla_role_members.ps1"),
        here.parents[2] / "scripts" / "xmla_role_members.ps1",
        Path.cwd() / "scripts" / "xmla_role_members.ps1",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise XmlaRolesError(
        f"xmla_role_members.ps1 not found. Set {SCRIPT_ENV} or reinstall fabric-tools.",
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


def resolve_timeout_seconds() -> float:
    """Return XMLA subprocess timeout (seconds); ``FABRIC_TOOLS_XMLA_TIMEOUT`` overrides."""
    raw = os.environ.get(TIMEOUT_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise XmlaRolesError(
            f"{TIMEOUT_ENV} must be a positive number of seconds (got {raw!r}).",
            code="invalid_timeout",
        ) from exc
    if value <= 0:
        raise XmlaRolesError(
            f"{TIMEOUT_ENV} must be > 0 (got {value}).",
            code="invalid_timeout",
        )
    return value


def resolve_connect_timeout_seconds(*, overall_timeout: float | None = None) -> int:
    """Return XMLA connect timeout; ``FABRIC_TOOLS_XMLA_CONNECT_TIMEOUT`` overrides.

    Clamped to ``[5, 600]`` and never above the overall subprocess timeout.
    """
    overall = (
        overall_timeout if overall_timeout is not None else resolve_timeout_seconds()
    )
    raw = os.environ.get(CONNECT_TIMEOUT_ENV)
    if raw is None or raw.strip() == "":
        value = float(DEFAULT_CONNECT_TIMEOUT_SECONDS)
    else:
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise XmlaRolesError(
                f"{CONNECT_TIMEOUT_ENV} must be a positive number of seconds "
                f"(got {raw!r}).",
                code="invalid_timeout",
            ) from exc
        if value <= 0:
            raise XmlaRolesError(
                f"{CONNECT_TIMEOUT_ENV} must be > 0 (got {value}).",
                code="invalid_timeout",
            )
    # Leave a little headroom for module load / JSON after connect.
    capped = min(value, max(5.0, overall - 5.0))
    return max(5, min(600, int(capped)))


def _parse_progress_stage(line: str) -> str | None:
    """Extract stage id from a ``##fabric-tools## stage=…`` stderr line."""
    text = line.strip()
    if not text.startswith(PROGRESS_PREFIX):
        return None
    rest = text[len(PROGRESS_PREFIX) :].strip()
    if rest.startswith("stage="):
        stage = rest[6:].strip()
        return stage or None
    return None


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    """Force-kill *proc* and any Windows child processes (hung .NET Connect, etc.)."""
    if sys.platform == "win32" and proc.pid:
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
    with contextlib.suppress(Exception):
        proc.kill()
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)


def _run_xmla_script(
    *,
    exe: str,
    script: Path,
    payload_json: str,
    timeout: float,
    on_progress: ProgressCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the XMLA script; kill the process tree on timeout or Ctrl+C.

    Arms a daemon kill-timer immediately after ``Popen`` (before stdin write) so a
    blocked pipe or hung native Connect cannot stall past the deadline. Stage
    lines are drained on the main thread so Rich spinner updates stay thread-safe.

    Avoid ``CREATE_NO_WINDOW`` on a TTY so console Ctrl+C can interrupt PowerShell.
    """
    creationflags = 0
    # Detached console children ignore Ctrl+C from the parent terminal.
    if not sys.stderr.isatty() and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(  # noqa: S603
        [
            exe,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    events: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stderr_chunks: list[str] = []
    last_stage: str | None = None
    stdout_box: list[str] = []
    finished = threading.Event()

    def _read_stderr() -> None:
        assert proc.stderr is not None
        try:
            for line in proc.stderr:
                stage = _parse_progress_stage(line)
                if stage is not None:
                    events.put(("stage", stage))
                else:
                    events.put(("stderr", line))
        finally:
            events.put(("stderr_eof", None))

    def _read_stdout() -> None:
        assert proc.stdout is not None
        try:
            stdout_box.append(proc.stdout.read() or "")
        finally:
            events.put(("stdout_eof", None))

    def _handle_event(kind: str, value: str | None) -> None:
        nonlocal last_stage
        if kind == "stage" and value:
            last_stage = value
            if on_progress is not None:
                on_progress(value)
        elif kind == "stderr" and value:
            stderr_chunks.append(value)

    def _kill_on_deadline() -> None:
        if finished.wait(timeout):
            return
        _kill_process_tree(proc)

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
    kill_thread = threading.Thread(target=_kill_on_deadline, daemon=True)
    stderr_thread.start()
    stdout_thread.start()
    kill_thread.start()

    timed_out = False
    try:
        assert proc.stdin is not None
        proc.stdin.write(payload_json)
        proc.stdin.close()

        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            while True:
                try:
                    kind, value = events.get_nowait()
                except queue.Empty:
                    break
                _handle_event(kind, value)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break

            try:
                kind, value = events.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            _handle_event(kind, value)

        if timed_out or proc.poll() is None:
            _kill_process_tree(proc)
            stage_hint = f" during stage '{last_stage}'" if last_stage else ""
            raise XmlaRolesError(
                f"XMLA role operation timed out after {timeout:g}s{stage_hint} "
                f"(set {TIMEOUT_ENV} / {CONNECT_TIMEOUT_ENV} to adjust limits).",
                code="timeout",
                stage=last_stage,
            )
    except KeyboardInterrupt:
        _kill_process_tree(proc)
        raise XmlaRolesError(
            "Aborted by user.",
            code="cancelled",
            stage=last_stage,
        ) from None
    finally:
        finished.set()
        stderr_thread.join(timeout=2)
        stdout_thread.join(timeout=2)
        kill_thread.join(timeout=1)

    while True:
        try:
            kind, value = events.get_nowait()
        except queue.Empty:
            break
        _handle_event(kind, value)

    stdout_text = stdout_box[0] if stdout_box else ""
    returncode = proc.returncode if proc.returncode is not None else -1
    # External connect-killer Stop-Process leaves empty stdout; surface a clear error.
    if returncode != 0 and not stdout_text.strip():
        stage = last_stage or "connecting"
        raise XmlaRolesError(
            f"XMLA process exited {returncode} during stage '{stage}' with no "
            f"response (connect hung or was killed). For My workspace confirm "
            f"Premium/PPU/Fabric capacity with XMLA read/write. "
            f"Adjust {CONNECT_TIMEOUT_ENV} / {TIMEOUT_ENV} if needed.",
            code="connect_failed",
            stage=stage,
            detail=("".join(stderr_chunks).strip() or None),
        )

    return subprocess.CompletedProcess(
        args=proc.args,
        returncode=returncode,
        stdout=stdout_text,
        stderr="".join(stderr_chunks),
    )


def _ps_run(
    script_block: str,
    *,
    powershell: str | None = None,
    timeout: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    exe = powershell or find_powershell()
    try:
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
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise XmlaRolesError(
            f"PowerShell helper timed out after {timeout:g}s.",
            code="timeout",
            stage="powershell_helper",
        ) from exc


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
    """Install SqlServer from PSGallery for the current user (can take minutes)."""
    from fabric_tools.status import busy, status_detail

    block = (
        f"Install-Module -Name {SQLSERVER_MODULE} -Scope CurrentUser "
        "-Repository PSGallery -Force -AllowClobber"
    )
    with busy(
        status_detail("semantic-model", "installing SqlServer module from PSGallery")
    ):
        result = _ps_run(block, powershell=powershell, timeout=INSTALL_TIMEOUT_SECONDS)
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

    Always stops any active spinner before prompting: a prompt printed under a
    live spinner is erased on the next refresh and looks like a hang.
    """
    if sqlserver_module_available(powershell=powershell):
        return

    hint = (
        f"{SQLSERVER_MODULE} PowerShell module not found. Install with: {INSTALL_HINT}"
    )
    if silent or not offer_install:
        raise XmlaRolesError(hint, code="module_missing")

    from fabric_tools.status import clear as clear_status

    clear_status()

    if confirm is None:
        import typer

        confirm = typer.confirm

    prompt = (
        f"{SQLSERVER_MODULE} PowerShell module not found. "
        f"Install from PSGallery for CurrentUser now?"
    )
    if not confirm(prompt, default=False):
        raise XmlaRolesError(
            f"Aborted by user. To install later, run: {INSTALL_HINT}",
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

    stage = str(data["stage"]) if data.get("stage") is not None else None
    result = XmlaRolesResult(
        ok=ok,
        changed=bool(data.get("changed")),
        message=str(data.get("message") or ""),
        roles=roles_list,
        code=str(data["code"]) if data.get("code") is not None else None,
        detail=str(data["detail"]) if data.get("detail") is not None else None,
        stage=stage,
        raw=data,
    )
    if not ok:
        raise XmlaRolesError(
            result.message or "XMLA role operation failed",
            code=result.code,
            detail=result.detail,
            stage=result.stage,
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
    workspace_type: str | None = None,
    data_source: str | None = None,
    offer_install: bool = True,
    silent: bool = False,
    confirm: Any | None = None,
    powershell: str | None = None,
    script_path: Path | None = None,
    on_progress: ProgressCallback | None = None,
    check_module: bool = True,
) -> XmlaRolesResult:
    """Run list / member_add / member_remove via the PowerShell TOM script.

    Pass ``check_module=False`` when the caller already ran
    :func:`ensure_sqlserver_module` (e.g. once before a batch, outside a spinner).
    """
    if sys.platform != "win32":
        raise XmlaRolesError(
            "XMLA role membership requires Windows PowerShell.",
            code="unsupported_platform",
        )

    if check_module:
        ensure_sqlserver_module(
            offer_install=offer_install,
            silent=silent,
            confirm=confirm,
            powershell=powershell,
        )

    script = script_path or resolve_script_path()
    exe = powershell or find_powershell()
    timeout = resolve_timeout_seconds()
    connect_timeout = resolve_connect_timeout_seconds(overall_timeout=timeout)
    # Fail fast on hung Connect: do not wait the full op timeout when connect is
    # the long pole (AMO often ignores Connect Timeout in the connection string).
    run_timeout = min(timeout, float(connect_timeout) + 5.0)

    if data_source is None:
        tenant_id: str | None = None
        owner: str | None = None
        if is_personal_workspace(
            workspace_type=workspace_type, display_name=workspace_name
        ):
            tenant_id, owner = personal_workspace_owner_from_token(access_token)
        data_source = workspace_xmla_connection(
            workspace_name,
            workspace_type=workspace_type,
            tenant_id=tenant_id,
            owner_upn_or_oid=owner,
        )

    payload: dict[str, Any] = {
        "action": action,
        "workspaceName": workspace_name,
        "databaseName": database_name,
        "accessToken": access_token,
        "connectTimeoutSeconds": connect_timeout,
        "dataSource": data_source,
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

    proc = _run_xmla_script(
        exe=exe,
        script=script,
        payload_json=json.dumps(payload),
        timeout=run_timeout,
        on_progress=on_progress,
    )
    return _parse_response(proc.stdout, proc.stderr, proc.returncode)
