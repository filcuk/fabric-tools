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


def _format_entry(spec: EnvVarSpec) -> str:
    raw = os.environ.get(spec.name)
    present = raw is not None and raw != ""

    if spec.kind == "flag":
        if not present:
            value_part = "(unset)"
            status = "unset"
        else:
            value_part = raw
            status = "enabled" if _flag_enabled(raw) else "set (not enabled)"
        return f"{spec.name}={value_part}\n  [{status}] {spec.description}"

    if spec.kind == "secret":
        value_part = "***" if present else "(unset)"
        status = "set" if present else "unset"
        return f"{spec.name}={value_part}\n  [{status}] {spec.description}"

    value_part = raw if present else "(unset)"
    status = "set" if present else "unset"
    return f"{spec.name}={value_part}\n  [{status}] {spec.description}"


def format_env_report() -> str:
    """Human-readable report of supported env vars and current process values."""
    lines = [_format_entry(spec) for spec in ENV_VAR_SPECS]

    from fabric_tools.auth import service_principal_configured

    sp = "configured" if service_principal_configured() else "not configured"
    readonly = "on" if is_readonly_enabled() else "off"
    lines.append("")
    lines.append(f"Effective: read-only={readonly}; service principal={sp}")
    return "\n".join(lines)
