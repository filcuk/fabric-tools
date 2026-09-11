"""Catalog and report for fabric-tools-supported environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from fabric_tools.readonly import READONLY_ENV, is_readonly_enabled
from fabric_tools.update_check import DISABLE_UPDATE_CHECK_ENV

EnvKind = Literal["flag", "value", "secret"]

_TRUTHY = frozenset({"1", "true", "yes", "on"})


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


# Keep in sync with README / AGENTS; used by ``fabric-tools env``.
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
