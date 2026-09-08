"""CLI argument parsing for notebook targets and files."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CommandMode(str, Enum):
    DOWNLOAD = "download"
    UPLOAD = "upload"
    COMPARE = "compare"


class ParseError(ValueError):
    """Invalid CLI targets/files combination."""


@dataclass(frozen=True)
class Target:
    workspace_id: str
    item_id: str | None = None

    @property
    def is_create(self) -> bool:
        return self.item_id is None

    def label(self) -> str:
        if self.item_id:
            return f"{self.workspace_id}:{self.item_id}"
        return self.workspace_id


@dataclass(frozen=True)
class WorkItem:
    target: Target | None
    file: Path | None


def parse_target_values(values: list[str] | None) -> list[Target]:
    """Parse repeatable/comma-separated ``--target`` values into Target objects."""
    if not values:
        return []
    targets: list[Target] = []
    for raw in values:
        for piece in _split_csv(raw):
            targets.append(_parse_one_target(piece))
    return targets


def parse_file_values(values: list[str] | None) -> list[Path]:
    """Parse repeatable/comma-separated ``--file`` values into Paths."""
    if not values:
        return []
    files: list[Path] = []
    for raw in values:
        for piece in _split_csv(raw):
            files.append(Path(piece))
    return files


def build_work_items(
    mode: CommandMode,
    targets: list[Target],
    files: list[Path],
    *,
    dry_run: bool,
) -> list[WorkItem]:
    """Validate mode rules and return paired work items."""
    if dry_run:
        return _build_dry_run_items(mode, targets, files)

    if not targets:
        raise ParseError("--target is required unless --dry-run is used with --file only")
    if not files:
        raise ParseError("--file is required unless --dry-run is used with --target only")

    if mode is CommandMode.DOWNLOAD:
        _require_items(targets, mode)
        _require_single_workspace(targets, mode)
        paired_files = _pair_files(targets, files, allow_broadcast=True)
        return [WorkItem(t, f) for t, f in zip(targets, paired_files, strict=True)]

    if mode is CommandMode.COMPARE:
        _require_items(targets, mode)
        _require_single_workspace(targets, mode)
        if len(files) != len(targets):
            raise ParseError(
                "compare requires a 1:1 match between --target and --file "
                f"(got {len(targets)} target(s) and {len(files)} file(s); broadcast is not allowed)"
            )
        return [WorkItem(t, f) for t, f in zip(targets, files, strict=True)]

    _require_homogeneous_upload(targets)
    paired_files = _pair_files(targets, files, allow_broadcast=True)
    return [WorkItem(t, f) for t, f in zip(targets, paired_files, strict=True)]


def _build_dry_run_items(
    mode: CommandMode,
    targets: list[Target],
    files: list[Path],
) -> list[WorkItem]:
    if not targets and not files:
        raise ParseError("--dry-run requires at least one --target or --file")

    if targets and files:
        return build_work_items(mode, targets, files, dry_run=False)

    if targets:
        if mode is CommandMode.DOWNLOAD:
            _require_items(targets, mode)
            _require_single_workspace(targets, mode)
        elif mode is CommandMode.COMPARE:
            _require_items(targets, mode)
            _require_single_workspace(targets, mode)
        elif mode is CommandMode.UPLOAD:
            _require_homogeneous_upload(targets)
        return [WorkItem(t, None) for t in targets]

    return [WorkItem(None, f) for f in files]


def _pair_files(
    targets: list[Target],
    files: list[Path],
    *,
    allow_broadcast: bool,
) -> list[Path]:
    if len(files) == len(targets):
        return list(files)
    if allow_broadcast and len(files) == 1 and len(targets) > 1:
        return [files[0]] * len(targets)
    raise ParseError(
        f"target/file count mismatch: {len(targets)} target(s), {len(files)} file(s). "
        "Use equal counts"
        + (", or one file to broadcast to all targets" if allow_broadcast else "")
        + "."
    )


def _require_items(targets: list[Target], mode: CommandMode) -> None:
    missing = [t.label() for t in targets if t.is_create]
    if missing:
        raise ParseError(
            f"{mode.value} requires workspace:artifact targets; "
            f"missing artifact id on: {', '.join(missing)}"
        )


def _require_single_workspace(targets: list[Target], mode: CommandMode) -> None:
    workspaces = {t.workspace_id for t in targets}
    if len(workspaces) > 1:
        raise ParseError(
            f"{mode.value} allows only one workspace; got {len(workspaces)}: "
            + ", ".join(sorted(workspaces))
        )


def _require_homogeneous_upload(targets: list[Target]) -> None:
    creates = [t for t in targets if t.is_create]
    updates = [t for t in targets if not t.is_create]
    if creates and updates:
        raise ParseError(
            "upload cannot mix create targets (workspace only) and overwrite "
            "targets (workspace:artifact) in one invocation"
        )


def _parse_one_target(value: str) -> Target:
    text = value.strip()
    if not text:
        raise ParseError("empty --target value")

    if ":" in text:
        workspace_raw, item_raw = text.split(":", 1)
        workspace_id = _parse_guid(workspace_raw.strip(), what="workspace id")
        item_raw = item_raw.strip()
        if not item_raw:
            return Target(workspace_id=workspace_id, item_id=None)
        item_id = _parse_guid(item_raw, what="artifact id")
        return Target(workspace_id=workspace_id, item_id=item_id)

    workspace_id = _parse_guid(text, what="workspace id")
    return Target(workspace_id=workspace_id, item_id=None)


def _parse_guid(value: str, *, what: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ParseError(f"invalid {what}: '{value}'") from exc


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]
