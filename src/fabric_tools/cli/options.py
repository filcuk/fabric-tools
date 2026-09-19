"""Shared CLI help strings and Typer Option factories.

Keep short/long flag pairs aligned with FLAGS.md. Kind-specific flags
(``--cells``, ``--publish``, ``--include-schedules``, ``--independent``, …)
stay in the command modules.
"""

from __future__ import annotations

from typing import Any

import typer

HELP_CONTEXT = {"help_option_names": ["--help", "-h"]}

# ---------------------------------------------------------------------------
# Shared help text (canonical; prefer these over per-command copies)
# ---------------------------------------------------------------------------

MANIFEST_HELP = (
    "(optional) Deployment manifest stem or path (.ftdep). "
    "Alone: load targets/origins (and local paths). With a successful run or dry-run: "
    "write/update the manifest."
)
MANIFEST_DELETE_HELP = (
    "(optional) Load workspace:artifact targets from a .ftdep "
    "(entries with itemId). Manifest is not rewritten after delete."
)
FILTER_HELP = (
    "(optional) Case-insensitive displayName substring; "
    "only valid with workspaceId:* on --origin or --target."
)
GUID_REMAP_HELP = (
    "(optional, deploy only) JSON file remapping source GUID → target GUID. "
    "Applied in memory to definition text before create/update "
    "(skips .platform). Repeatable or comma-separated; one file may broadcast "
    "to all targets, or pair 1:1 with targets."
)
SILENT_HELP = "(optional) Skip confirmation prompts."

ORIGIN_DOWNLOAD_HELP = (
    "(required without -m or -d) Remote workspace:artifact to download. "
    "Repeatable or comma-separated (spaces after commas OK). One workspace only."
)
TARGET_DOWNLOAD_HELP = (
    "(optional) Local destination path. "
    "Defaults to remote display name with the kind extension in the current folder. "
    "Repeatable or comma-separated (spaces after commas OK). "
    "One path may broadcast to all origins."
)

TARGET_DEPLOY_HELP = (
    "(required without -m or -d) workspace GUID (create) or "
    "workspace:artifact (overwrite). Repeatable or comma-separated "
    "(spaces after commas OK)."
)
ORIGIN_DEPLOY_HELP = (
    "(required without -m or -d) Local path or remote workspace:artifact source. "
    "Repeatable or comma-separated (spaces after commas OK). "
    "One origin may broadcast to all targets."
)
NAME_DEPLOY_HELP = (
    "(optional, create only) Display name. Defaults to file/folder stem "
    "or origin display name."
)

TARGET_COMPARE_HELP = (
    "(required without -m or -d) workspace:artifact GUID. "
    "Repeatable or comma-separated (spaces after commas OK)."
)
ORIGIN_COMPARE_HELP = (
    "(required without -m or -d) Local path or remote workspace:artifact to compare "
    "against --target. Must 1:1 match --target (no broadcast)."
)

TARGET_DELETE_HELP = (
    "(required without -m or -d) workspace:artifact GUID. "
    "Repeatable or comma-separated (spaces after commas OK). "
    "Also accepts workspaceId:* (all items of this kind)."
)

DRY_RUN_DOWNLOAD_HELP = (
    "(optional) Validate targets and/or files only; do not download."
)
DRY_RUN_DEPLOY_HELP = "(optional) Validate targets and/or sources only; do not deploy."
DRY_RUN_COMPARE_HELP = (
    "(optional) Validate targets and/or sources only; do not compare."
)
DRY_RUN_DELETE_HELP = "(optional) Validate targets only; do not delete."

# ---------------------------------------------------------------------------
# Option factories
# ---------------------------------------------------------------------------


def origin_opt(*, help: str) -> Any:
    return typer.Option(None, "--origin", "-o", help=help)


def target_opt(*, help: str, required: bool = False) -> Any:
    default: Any = ... if required else None
    return typer.Option(default, "--target", "-t", help=help)


def manifest_opt(*, help: str = MANIFEST_HELP, required: bool = False) -> Any:
    default: Any = ... if required else None
    return typer.Option(default, "--manifest", "-m", help=help)


def filter_opt(*, help: str = FILTER_HELP) -> Any:
    return typer.Option(None, "--filter", "-f", help=help)


def silent_opt(*, help: str = SILENT_HELP) -> Any:
    return typer.Option(False, "--silent", "-s", help=help)


def dry_run_opt(*, help: str) -> Any:
    return typer.Option(False, "--dry-run", "-d", help=help)


def name_opt(*, help: str = NAME_DEPLOY_HELP) -> Any:
    return typer.Option(None, "--name", "-n", help=help)


def remap_opt(*, help: str = GUID_REMAP_HELP) -> Any:
    return typer.Option(None, "--remap", "-r", help=help)
