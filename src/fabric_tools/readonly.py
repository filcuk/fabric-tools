"""Read-only guard for agent-safe / non-mutating sessions."""

from __future__ import annotations

import os

from fabric_tools.parsing import CommandMode

READONLY_ENV = "FABRIC_TOOLS_READONLY"

# Modes that change remote Fabric / Power BI state when not --dry-run.
_MUTATING_MODES = frozenset({CommandMode.DEPLOY, CommandMode.DELETE})


class ReadOnlyError(RuntimeError):
    """Raised when ``FABRIC_TOOLS_READONLY`` blocks a mutating action."""


def is_readonly_enabled() -> bool:
    """True when ``FABRIC_TOOLS_READONLY`` is set to a truthy value."""
    value = os.environ.get(READONLY_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def ensure_command_allowed(mode: CommandMode, *, dry_run: bool) -> None:
    """Refuse deploy/delete execute when read-only is enabled.

    ``--dry-run``, download, and compare are always allowed.
    ``--silent`` does not override this guard.
    """
    if dry_run or not is_readonly_enabled():
        return
    if mode not in _MUTATING_MODES:
        return
    raise ReadOnlyError(
        f"Refusing {mode.value}: {READONLY_ENV} is set. "
        "Unset it, or use --dry-run to validate without changes."
    )


def ensure_setup_mutation_allowed(action: str) -> None:
    """Refuse mutating setup actions when read-only."""
    if not is_readonly_enabled():
        return
    raise ReadOnlyError(
        f"Refusing setup {action}: {READONLY_ENV} is set. "
        "Unset it to allow install, update, uninstall, or clean "
        "(setup status and setup update --check remain allowed)."
    )
