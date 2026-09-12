"""Catalog, report, and user-environment set/unset for supported env vars."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from fabric_tools.readonly import READONLY_ENV, is_readonly_enabled
from fabric_tools.update_check import DISABLE_UPDATE_CHECK_ENV

EnvKind = Literal["flag", "value", "secret"]

_TRUTHY = frozenset({"1", "true", "yes", "on"})


class EnvError(RuntimeError):
    """Invalid env name or user-environment update failure."""


@dataclass(frozen=True)
class EnvVarSpec:
    """One supported environment variable."""

    name: str
    description: str
    kind: EnvKind


@dataclass(frozen=True)
class EnvVarStatus:
    """Resolved display fields for one env var in the current process."""

    name: str
    value: str
    status: str
    description: str
    kind: EnvKind


# Keep in sync with README / AGENTS; used by ``fabric-tools env list``.
ENV_VAR_SPECS: tuple[EnvVarSpec, ...] = (
    EnvVarSpec(
        READONLY_ENV,
        "Refuse deploy/delete execute and mutating setup "
        "(install / update / uninstall).",
        "flag",
    ),
    EnvVarSpec(
        DISABLE_UPDATE_CHECK_ENV,
        "Disable once-per-day background update notice.",
        "flag",
    ),
    EnvVarSpec(
        "AZURE_TENANT_ID",
        "Service principal tenant (with CLIENT_ID and CLIENT_SECRET).",
        "value",
    ),
    EnvVarSpec(
        "AZURE_CLIENT_ID",
        "Service principal application (client) id.",
        "value",
    ),
    EnvVarSpec(
        "AZURE_CLIENT_SECRET",
        "Service principal secret (value never printed).",
        "secret",
    ),
)

_SPECS_BY_NAME = {spec.name: spec for spec in ENV_VAR_SPECS}


def get_spec(name: str) -> EnvVarSpec:
    """Return the catalog entry for *name* or raise ``EnvError``."""
    spec = _SPECS_BY_NAME.get(name)
    if spec is None:
        known = ", ".join(spec.name for spec in ENV_VAR_SPECS)
        raise EnvError(f"Unknown environment variable {name!r}. Supported: {known}")
    return spec


def _flag_enabled(raw: str) -> bool:
    return raw.strip().lower() in _TRUTHY


def _resolve_status(spec: EnvVarSpec) -> EnvVarStatus:
    raw = os.environ.get(spec.name)
    present = raw is not None and raw != ""

    if spec.kind == "flag":
        if not present:
            value, status = "(unset)", "unset"
        else:
            value = raw
            status = "enabled" if _flag_enabled(raw) else "set (not enabled)"
    elif spec.kind == "secret":
        value = "***" if present else "(unset)"
        status = "set" if present else "unset"
    else:
        value = raw if present else "(unset)"
        status = "set" if present else "unset"

    return EnvVarStatus(
        name=spec.name,
        value=value,
        status=status,
        description=spec.description,
        kind=spec.kind,
    )


def collect_env_statuses() -> list[EnvVarStatus]:
    """Resolve all catalogued env vars against the current process environment."""
    return [_resolve_status(spec) for spec in ENV_VAR_SPECS]


def _status_style(status: str) -> str:
    if status in {"enabled", "set"}:
        return "green"
    if status == "set (not enabled)":
        return "yellow"
    return "cyan"


def print_env_report() -> None:
    """Print supported env vars and current values (plain lines, light color)."""
    from rich.console import Console
    from rich.text import Text

    from fabric_tools.auth import service_principal_configured

    rows = collect_env_statuses()
    name_w = max(len(row.name) for row in rows)
    value_w = max(len(row.value) for row in rows)
    status_w = max(len(row.status) for row in rows)
    console = Console()

    for row in rows:
        line = Text()
        line.append(f"{row.name:<{name_w}}  {row.value:<{value_w}}  ")
        line.append(f"{row.status:<{status_w}}", style=_status_style(row.status))
        line.append(f"  {row.description}")
        console.print(line)

    readonly = is_readonly_enabled()
    sp = service_principal_configured()
    summary = Text("\nEffective: read-only=")
    summary.append(
        "on" if readonly else "off",
        style="green" if readonly else "cyan",
    )
    summary.append("; service principal=")
    summary.append(
        "configured" if sp else "not configured",
        style="green" if sp else "cyan",
    )
    console.print(summary)


def set_user_env(name: str, value: str) -> EnvVarSpec:
    """Persist *name*=*value* in the user environment (Windows) and this process."""
    spec = get_spec(name)
    if value == "":
        raise EnvError(
            f"Empty value for {spec.name}; use 'fabric-tools env unset {spec.name}' "
            "to remove it."
        )
    _write_user_env(spec.name, value)
    os.environ[spec.name] = value
    return spec


def unset_user_env(name: str) -> EnvVarSpec:
    """Remove *name* from the user environment (Windows) and this process."""
    spec = get_spec(name)
    _delete_user_env(spec.name)
    os.environ.pop(spec.name, None)
    return spec


def _require_windows() -> None:
    if os.name != "nt":
        raise EnvError(
            "Setting or unsetting user environment variables is only supported "
            "on Windows."
        )


def _write_user_env(name: str, value: str) -> None:
    _require_windows()
    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except OSError as exc:
        raise EnvError(
            f"Failed to set user environment variable {name}: {exc}"
        ) from exc
    _broadcast_env_change()


def _delete_user_env(name: str) -> None:
    _require_windows()
    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                return
    except OSError as exc:
        raise EnvError(
            f"Failed to unset user environment variable {name}: {exc}"
        ) from exc
    _broadcast_env_change()


def _broadcast_env_change() -> None:
    """Notify the system that user environment variables changed."""
    # Reuse the same best-effort broadcast as PATH install.
    from fabric_tools.path_setup import _broadcast_env_change as broadcast

    broadcast()


def format_set_confirmation(spec: EnvVarSpec, value: str) -> str:
    """User-facing confirmation after set (secrets never include the value)."""
    if spec.kind == "secret":
        detail = f"Set {spec.name} in your user environment (value hidden)."
    else:
        detail = f"Set {spec.name}={value} in your user environment."
    return (
        f"{detail}\n"
        "Open a new terminal (restart your IDE if needed) for other apps/shells "
        "to see the change."
    )


def format_unset_confirmation(spec: EnvVarSpec) -> str:
    """User-facing confirmation after unset."""
    return (
        f"Unset {spec.name} from your user environment.\n"
        "Open a new terminal (restart your IDE if needed) for other apps/shells "
        "to see the change."
    )
