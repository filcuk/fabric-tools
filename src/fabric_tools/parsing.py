"""CLI argument parsing for targets, files, and origins."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Options that accept comma-separated lists (spaces after commas are common).
_CSV_OPTION_FLAGS = frozenset(
    {
        "-t",
        "--target",
        "-f",
        "--file",
        "-o",
        "--origin",
        "-c",
        "--cells",
    }
)


class CommandMode(str, Enum):
    DOWNLOAD = "download"
    DEPLOY = "deploy"
    COMPARE = "compare"
    DELETE = "delete"


class ParseError(ValueError):
    """Invalid CLI targets/files/origins combination."""


def rejoin_spaced_csv_argv(argv: list[str]) -> list[str]:
    """Rejoin shell-split ``--target a, b, c`` style CSV option values.

    Unquoted commas followed by spaces become separate argv tokens; Click then
    treats the trailing pieces as unexpected positional arguments. Merge those
    pieces back into one option value when the previous token ends with ``,``.
    """
    if not argv:
        return []

    result: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        result.append(token)

        if "=" in token and token.startswith("-"):
            # Already ``--opt=value`` (one token); leave as-is.
            i += 1
            continue

        if token in _CSV_OPTION_FLAGS and i + 1 < len(argv):
            i += 1
            chunks = [argv[i]]
            while i + 1 < len(argv) and _is_csv_value_continuation(
                argv[i], argv[i + 1]
            ):
                i += 1
                chunks.append(argv[i])
            result.append(" ".join(chunks))
        i += 1
    return result


def _is_csv_value_continuation(prev: str, nxt: str) -> bool:
    if not nxt or nxt.startswith("-"):
        return False
    return prev.rstrip().endswith(",")


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
    origin: Target | None = None


def parse_target_values(values: list[str] | None) -> list[Target]:
    """Parse repeatable/comma-separated ``--target`` values into Target objects.

    Within one flag value, bare artifact GUIDs after ``workspace:artifact`` inherit
    that workspace. Overwrite-scoped values must use a single workspace; create CSV
    may list multiple workspaces.
    """
    if not values:
        return []
    targets: list[Target] = []
    for raw in values:
        targets.extend(
            _expand_scoped_targets(raw, allow_create=True, option="--target")
        )
    return targets


def parse_origin_values(values: list[str] | None) -> list[Target]:
    """Parse repeatable/comma-separated ``--origin`` values (workspace:artifact only).

    Same per-flag shorthand as targets; each overwrite-scoped value is one workspace.
    """
    if not values:
        return []
    origins: list[Target] = []
    for raw in values:
        origins.extend(
            _expand_scoped_targets(raw, allow_create=False, option="--origin")
        )
    return origins


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
    origins: list[Target] | None = None,
    dry_run: bool,
    deploy_create_only: bool = False,
) -> list[WorkItem]:
    """Validate mode rules and return paired work items.

    When ``deploy_create_only`` is True, deploy targets must be workspace-only
    (no artifact id). Used by Dataflow Gen1 (no overwrite).
    """
    origin_list = list(origins) if origins else []
    if dry_run:
        return _build_dry_run_items(
            mode,
            targets,
            files,
            origin_list,
            deploy_create_only=deploy_create_only,
        )

    if not targets:
        raise ParseError(
            "--target is required unless --dry-run is used with --file/--origin only"
        )

    if mode is CommandMode.DELETE:
        if files or origin_list:
            raise ParseError("delete does not support --file or --origin")
        _require_items(targets, mode)
        return [WorkItem(t, None) for t in targets]

    allow_neither = mode is CommandMode.DOWNLOAD
    _require_exclusive_source(files, origin_list, allow_neither=allow_neither)

    if mode is CommandMode.DOWNLOAD:
        if origin_list:
            raise ParseError(
                "download does not support --origin (use --file destination)"
            )
        _require_items(targets, mode)
        _require_single_workspace(targets, mode)
        if not files:
            # Destination defaults to remote display name + extension at download time.
            return [WorkItem(t, None) for t in targets]
        paired_files = _pair_sources(targets, files, allow_broadcast=True, kind="file")
        return [WorkItem(t, f) for t, f in zip(targets, paired_files, strict=True)]

    if mode is CommandMode.COMPARE:
        _require_items(targets, mode)
        if files:
            _require_single_workspace(targets, mode)
            if len(files) != len(targets):
                raise ParseError(
                    "compare requires a 1:1 match between --target and --file "
                    f"(got {len(targets)} target(s) and {len(files)} file(s); "
                    "broadcast is not allowed)"
                )
            return [WorkItem(t, f) for t, f in zip(targets, files, strict=True)]
        if len(origin_list) != len(targets):
            raise ParseError(
                "compare requires a 1:1 match between --target and --origin "
                f"(got {len(targets)} target(s) and {len(origin_list)} origin(s); "
                "broadcast is not allowed)"
            )
        return [
            WorkItem(t, None, origin=o)
            for t, o in zip(targets, origin_list, strict=True)
        ]

    # DEPLOY
    if deploy_create_only:
        _require_create_only_deploy(targets)
    else:
        _require_homogeneous_deploy(targets)
    if files:
        paired_files = _pair_sources(targets, files, allow_broadcast=True, kind="file")
        return [WorkItem(t, f) for t, f in zip(targets, paired_files, strict=True)]
    paired_origins = _pair_sources(
        targets, origin_list, allow_broadcast=True, kind="origin"
    )
    return [
        WorkItem(t, None, origin=o)
        for t, o in zip(targets, paired_origins, strict=True)
    ]


def _build_dry_run_items(
    mode: CommandMode,
    targets: list[Target],
    files: list[Path],
    origins: list[Target],
    *,
    deploy_create_only: bool = False,
) -> list[WorkItem]:
    if mode is CommandMode.DELETE:
        if files or origins:
            raise ParseError("delete does not support --file or --origin")
        if not targets:
            raise ParseError("--dry-run delete requires at least one --target")
        _require_items(targets, mode)
        return [WorkItem(t, None) for t in targets]

    if not targets and not files and not origins:
        raise ParseError(
            "--dry-run requires at least one --target, --file, or --origin"
        )

    _require_exclusive_source(files, origins, allow_neither=True)

    if targets and (files or origins):
        return build_work_items(
            mode,
            targets,
            files,
            origins=origins,
            dry_run=False,
            deploy_create_only=deploy_create_only,
        )

    if targets:
        if mode is CommandMode.DOWNLOAD or mode is CommandMode.COMPARE:
            _require_items(targets, mode)
            _require_single_workspace(targets, mode)
        elif mode is CommandMode.DEPLOY:
            if deploy_create_only:
                _require_create_only_deploy(targets)
            else:
                _require_homogeneous_deploy(targets)
        return [WorkItem(t, None) for t in targets]

    if files:
        return [WorkItem(None, f) for f in files]

    return [WorkItem(None, None, origin=o) for o in origins]


def _require_exclusive_source(
    files: list[Path],
    origins: list[Target],
    *,
    allow_neither: bool,
) -> None:
    if files and origins:
        raise ParseError("use either --file or --origin, not both")
    if not allow_neither and not files and not origins:
        raise ParseError("either --file or --origin is required")


def _pair_sources(
    targets: list[Target],
    sources: list,
    *,
    allow_broadcast: bool,
    kind: str,
) -> list:
    if len(sources) == len(targets):
        return list(sources)
    if allow_broadcast and len(sources) == 1 and len(targets) > 1:
        return [sources[0]] * len(targets)
    raise ParseError(
        f"target/{kind} count mismatch: {len(targets)} target(s), {len(sources)} {kind}(s). "
        "Use equal counts"
        + (f", or one {kind} to broadcast to all targets" if allow_broadcast else "")
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


def _require_homogeneous_deploy(targets: list[Target]) -> None:
    creates = [t for t in targets if t.is_create]
    updates = [t for t in targets if not t.is_create]
    if creates and updates:
        raise ParseError(
            "deploy cannot mix create targets (workspace only) and overwrite "
            "targets (workspace:artifact) in one invocation"
        )


def _require_create_only_deploy(targets: list[Target]) -> None:
    updates = [t.label() for t in targets if not t.is_create]
    if updates:
        raise ParseError(
            "dataflow-gen1 deploy supports create only (workspace targets); "
            f"got artifact target(s): {', '.join(updates)}"
        )


def _expand_scoped_targets(
    raw: str,
    *,
    allow_create: bool,
    option: str,
) -> list[Target]:
    """Expand one flag value with optional workspace shorthand for bare GUIDs."""
    pieces = _split_csv(raw)
    if not pieces:
        raise ParseError(f"empty {option} value")

    targets: list[Target] = []
    current_ws: str | None = None

    for piece in pieces:
        if ":" in piece:
            workspace_raw, item_raw = piece.split(":", 1)
            workspace_id = _parse_guid(workspace_raw.strip(), what="workspace id")
            item_raw = item_raw.strip()
            if not item_raw:
                if not allow_create:
                    raise ParseError(
                        f"{option} requires workspace:artifact; "
                        f"missing artifact id on '{piece}'"
                    )
                targets.append(Target(workspace_id=workspace_id, item_id=None))
                continue
            item_id = _parse_guid(item_raw, what="artifact id")
            targets.append(Target(workspace_id=workspace_id, item_id=item_id))
            current_ws = workspace_id
            continue

        bare_id = _parse_guid(
            piece, what="workspace id" if current_ws is None else "artifact id"
        )
        if current_ws is not None:
            targets.append(Target(workspace_id=current_ws, item_id=bare_id))
            continue
        if not allow_create:
            raise ParseError(
                f"{option} requires workspace:artifact; got '{piece}' "
                "(workspace only is not allowed)"
            )
        targets.append(Target(workspace_id=bare_id, item_id=None))

    if any(not t.is_create for t in targets):
        workspaces = {t.workspace_id for t in targets}
        if len(workspaces) > 1:
            raise ParseError(
                f"one {option} value may only refer to one workspace for "
                f"overwrite targets; got {len(workspaces)}: "
                + ", ".join(sorted(workspaces))
                + ". Use separate flags per workspace."
            )
    return targets


def _parse_guid(value: str, *, what: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ParseError(f"invalid {what}: '{value}'") from exc


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')


def sanitize_download_filename(name: str) -> str:
    """Make a remote display name safe as a single path segment."""
    cleaned = "".join(
        "_" if (ch in _INVALID_FILENAME_CHARS or ord(ch) < 32) else ch
        for ch in name.strip()
    )
    cleaned = cleaned.rstrip(" .")
    return cleaned or "download"


def default_download_paths(
    display_names: list[str],
    *,
    extension: str,
) -> list[Path]:
    """Build unique cwd-relative paths from display names and an extension.

    ``extension`` should include the dot (e.g. ``.ipynb``, ``.json``). Duplicate
    names in the same batch get `` (2)``, `` (3)``, … suffixes before the extension.
    """
    if not extension.startswith("."):
        extension = f".{extension}"
    used: set[str] = set()
    paths: list[Path] = []
    for raw_name in display_names:
        stem = sanitize_download_filename(raw_name)
        candidate = f"{stem}{extension}"
        n = 2
        while candidate.casefold() in used:
            candidate = f"{stem} ({n}){extension}"
            n += 1
        used.add(candidate.casefold())
        paths.append(Path(candidate))
    return paths
