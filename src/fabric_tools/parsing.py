"""CLI argument parsing for polymorphic --origin / --target endpoints."""

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
        "-o",
        "--origin",
        "-c",
        "--cells",
        "--remap",
        "-r",
    }
)


class CommandMode(str, Enum):
    DOWNLOAD = "download"
    DEPLOY = "deploy"
    COMPARE = "compare"
    DELETE = "delete"


class ParseError(ValueError):
    """Invalid CLI origin/target combination."""


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
    wildcard: bool = False

    @property
    def is_create(self) -> bool:
        return self.item_id is None and not self.wildcard

    @property
    def is_wildcard(self) -> bool:
        return self.wildcard

    def label(self) -> str:
        if self.wildcard:
            return f"{self.workspace_id}:*"
        if self.item_id:
            return f"{self.workspace_id}:{self.item_id}"
        return self.workspace_id


@dataclass(frozen=True)
class WorkItem:
    """Internal work unit.

    ``target`` is the tracked remote (download source remote, or deploy/compare/delete
    destination remote). ``file`` is a local path. ``origin`` is a remote-to-remote
    source when present.
    """

    target: Target | None
    file: Path | None
    origin: Target | None = None


@dataclass(frozen=True)
class ClassifiedEndpoints:
    """Parsed ``--origin`` / ``--target`` values after remote-vs-path classification."""

    origin_remotes: list[Target]
    origin_paths: list[Path]
    target_remotes: list[Target]
    target_paths: list[Path]


def parse_target_values(
    values: list[str] | None,
    *,
    allow_create: bool = True,
) -> list[Target]:
    """Parse repeatable/comma-separated remote ``--target`` values into Target objects.

    Prefer :func:`classify_endpoint_values` for polymorphic CLI parsing. This helper
    remains for callers that already know values are remotes (e.g. manifests).
    """
    if not values:
        return []
    remotes, paths = classify_endpoint_values(
        values, option="--target", allow_create=allow_create
    )
    if paths:
        raise ParseError(
            f"--target expected remote selector(s); got local path(s): "
            f"{', '.join(str(p) for p in paths)}"
        )
    return remotes


def parse_origin_values(values: list[str] | None) -> list[Target]:
    """Parse repeatable/comma-separated remote ``--origin`` values (workspace:artifact).

    Prefer :func:`classify_endpoint_values` for polymorphic CLI parsing.
    """
    if not values:
        return []
    remotes, paths = classify_endpoint_values(
        values, option="--origin", allow_create=False
    )
    if paths:
        raise ParseError(
            f"--origin expected remote selector(s); got local path(s): "
            f"{', '.join(str(p) for p in paths)}"
        )
    return remotes


def parse_file_values(values: list[str] | None) -> list[Path]:
    """Parse repeatable/comma-separated local path values into Paths."""
    if not values:
        return []
    files: list[Path] = []
    for raw in values:
        for piece in _split_csv(raw):
            files.append(Path(piece))
    return files


def classify_endpoint_values(
    values: list[str] | None,
    *,
    option: str,
    allow_create: bool,
) -> tuple[list[Target], list[Path]]:
    """Classify repeatable/CSV ``--origin`` or ``--target`` values as remotes or paths.

    Each flag occurrence must be entirely remotes or entirely paths (no mix inside
    one CSV). Across occurrences, the combined result must also be a single kind.
    """
    if not values:
        return [], []

    remotes: list[Target] = []
    paths: list[Path] = []
    kind: str | None = None

    for raw in values:
        piece_remotes, piece_paths = _classify_one_flag_value(
            raw, option=option, allow_create=allow_create
        )
        if piece_remotes and piece_paths:
            raise ParseError(
                f"{option} value mixes remote selectors and local paths: '{raw}'"
            )
        if piece_remotes:
            if kind == "path":
                raise ParseError(
                    f"{option} cannot mix remote selectors and local paths "
                    "across repeated flags"
                )
            kind = "remote"
            remotes.extend(piece_remotes)
        elif piece_paths:
            if kind == "remote":
                raise ParseError(
                    f"{option} cannot mix remote selectors and local paths "
                    "across repeated flags"
                )
            kind = "path"
            paths.extend(piece_paths)

    return remotes, paths


def classify_cli_endpoints(
    *,
    origin_values: list[str] | None,
    target_values: list[str] | None,
    mode: CommandMode,
) -> ClassifiedEndpoints:
    """Classify CLI ``--origin`` / ``--target`` for *mode* (create allowed on deploy targets)."""
    origin_allow_create = False
    target_allow_create = mode is CommandMode.DEPLOY
    origin_remotes, origin_paths = classify_endpoint_values(
        origin_values, option="--origin", allow_create=origin_allow_create
    )
    target_remotes, target_paths = classify_endpoint_values(
        target_values, option="--target", allow_create=target_allow_create
    )
    return ClassifiedEndpoints(
        origin_remotes=origin_remotes,
        origin_paths=origin_paths,
        target_remotes=target_remotes,
        target_paths=target_paths,
    )


def build_work_items(
    mode: CommandMode,
    targets: list[Target],
    files: list[Path],
    *,
    origins: list[Target] | None = None,
    dry_run: bool,
    deploy_create_only: bool = False,
) -> list[WorkItem]:
    """Validate mode rules and return paired work items (internal remote/file/origin shape).

    When ``deploy_create_only`` is True, deploy targets must be workspace-only
    (no artifact id). Used by Dataflow Gen1 (no overwrite).

    Callers with polymorphic CLI flags should use :func:`build_work_items_from_cli`.
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
            "--target is required unless --dry-run is used with --origin only"
        )

    if mode is CommandMode.DELETE:
        if files or origin_list:
            raise ParseError("delete does not support --origin local paths or remotes")
        _require_items(targets, mode)
        return [WorkItem(t, None) for t in targets]

    allow_neither = mode is CommandMode.DOWNLOAD
    _require_exclusive_source(files, origin_list, allow_neither=allow_neither)

    if mode is CommandMode.DOWNLOAD:
        if origin_list:
            raise ParseError(
                "download does not support a remote --origin as a second source; "
                "use --origin for the remote to pull and optional --target for the "
                "local path"
            )
        _require_items(targets, mode)
        _require_single_workspace(targets, mode)
        if not files:
            # Destination defaults to remote display name + extension at download time.
            return [WorkItem(t, None) for t in targets]
        paired_files = _pair_sources(
            targets, files, allow_broadcast=True, kind="target path"
        )
        return [WorkItem(t, f) for t, f in zip(targets, paired_files, strict=True)]

    if mode is CommandMode.COMPARE:
        _require_items(targets, mode)
        if files:
            _require_single_workspace(targets, mode)
            if len(files) != len(targets):
                raise ParseError(
                    "compare requires a 1:1 match between --target and --origin "
                    f"(got {len(targets)} target(s) and {len(files)} origin path(s); "
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
        paired_files = _pair_sources(
            targets, files, allow_broadcast=True, kind="origin path"
        )
        return [WorkItem(t, f) for t, f in zip(targets, paired_files, strict=True)]
    paired_origins = _pair_sources(
        targets, origin_list, allow_broadcast=True, kind="origin"
    )
    return [
        WorkItem(t, None, origin=o)
        for t, o in zip(targets, paired_origins, strict=True)
    ]


def build_work_items_from_cli(
    mode: CommandMode,
    *,
    origin_values: list[str] | None,
    target_values: list[str] | None,
    dry_run: bool,
    deploy_create_only: bool = False,
) -> list[WorkItem]:
    """Build work items from polymorphic CLI ``--origin`` / ``--target`` values."""
    classified = classify_cli_endpoints(
        origin_values=origin_values,
        target_values=target_values,
        mode=mode,
    )
    return build_work_items_from_classified(
        mode,
        classified,
        dry_run=dry_run,
        deploy_create_only=deploy_create_only,
    )


def build_work_items_from_classified(
    mode: CommandMode,
    classified: ClassifiedEndpoints,
    *,
    dry_run: bool,
    deploy_create_only: bool = False,
) -> list[WorkItem]:
    """Map classified CLI endpoints onto the internal WorkItem shape."""
    o_rem = classified.origin_remotes
    o_path = classified.origin_paths
    t_rem = classified.target_remotes
    t_path = classified.target_paths

    if mode is CommandMode.DELETE:
        if o_rem or o_path or t_path:
            raise ParseError("delete only accepts remote --target selector(s)")
        return build_work_items(
            mode,
            t_rem,
            [],
            origins=None,
            dry_run=dry_run,
            deploy_create_only=deploy_create_only,
        )

    if mode is CommandMode.DOWNLOAD:
        if o_path:
            raise ParseError(
                "download --origin must be a remote selector (workspace:artifact)"
            )
        if t_rem:
            raise ParseError(
                "download --target must be a local path when set "
                "(remote to pull belongs in --origin)"
            )
        if not dry_run and not o_rem:
            raise ParseError("download requires --origin remote selector(s)")
        # Internal: tracked remote is WorkItem.target; local dest is WorkItem.file.
        return build_work_items(
            mode,
            o_rem,
            t_path,
            origins=None,
            dry_run=dry_run,
            deploy_create_only=deploy_create_only,
        )

    # deploy / compare
    if t_path:
        raise ParseError(
            f"{mode.value} --target must be a remote selector "
            "(local paths belong in --origin)"
        )
    if o_rem and o_path:
        raise ParseError("use either a local path or a remote --origin, not both")

    if not dry_run and not t_rem:
        raise ParseError(f"{mode.value} requires remote --target selector(s)")

    if o_path:
        return build_work_items(
            mode,
            t_rem,
            o_path,
            origins=None,
            dry_run=dry_run,
            deploy_create_only=deploy_create_only,
        )
    return build_work_items(
        mode,
        t_rem,
        [],
        origins=o_rem,
        dry_run=dry_run,
        deploy_create_only=deploy_create_only,
    )


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
            raise ParseError("delete does not support --origin local paths or remotes")
        if not targets:
            raise ParseError("--dry-run delete requires at least one --target")
        _require_items(targets, mode)
        return [WorkItem(t, None) for t in targets]

    if not targets and not files and not origins:
        raise ParseError("--dry-run requires at least one --target or --origin")

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
        raise ParseError("use either a local path or a remote --origin, not both")
    if not allow_neither and not files and not origins:
        raise ParseError(
            "either a local --origin path or a remote --origin is required"
        )


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
        f"target/{kind} count mismatch: {len(targets)} target(s), "
        f"{len(sources)} {kind}(s). "
        "Use equal counts"
        + (f", or one {kind} to broadcast to all targets" if allow_broadcast else "")
        + "."
    )


def _require_items(targets: list[Target], mode: CommandMode) -> None:
    wildcards = [t.label() for t in targets if t.wildcard]
    if wildcards:
        raise ParseError(
            f"{mode.value} received unexpanded workspace:* selector(s): "
            f"{', '.join(wildcards)}"
        )
    missing = [t.label() for t in targets if t.is_create]
    if missing:
        raise ParseError(
            f"{mode.value} requires workspace:artifact; "
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
    wildcards = [t.label() for t in targets if t.wildcard]
    if wildcards:
        raise ParseError(
            "dataflow-gen1 deploy supports create only (workspace targets); "
            f"got workspace:* selector(s): {', '.join(wildcards)}"
        )
    updates = [t.label() for t in targets if not t.is_create]
    if updates:
        raise ParseError(
            "dataflow-gen1 deploy supports create only (workspace targets); "
            f"got artifact target(s): {', '.join(updates)}"
        )


def _classify_one_flag_value(
    raw: str,
    *,
    option: str,
    allow_create: bool,
) -> tuple[list[Target], list[Path]]:
    pieces = _split_csv(raw)
    if not pieces:
        raise ParseError(f"empty {option} value")

    remotes: list[Target] = []
    paths: list[Path] = []
    current_ws: str | None = None

    for piece in pieces:
        remote = _try_parse_remote_token(
            piece, allow_create=allow_create, current_ws=current_ws, option=option
        )
        if remote is not None:
            remotes.append(remote)
            if not remote.is_create:
                current_ws = remote.workspace_id
            continue
        if _looks_like_failed_remote(piece):
            raise ParseError(f"invalid {option} remote selector: '{piece}'")
        paths.append(Path(piece))
        current_ws = None

    if remotes and paths:
        return remotes, paths

    if remotes:
        _validate_single_workspace_overwrite(remotes, option=option)
    return remotes, paths


def _looks_like_failed_remote(piece: str) -> bool:
    """True when *piece* looks like a remote selector that should not be a path."""
    text = piece.strip()
    if ":" not in text:
        return _is_guid(text)
    left, right = text.split(":", 1)
    return _is_guid(left.strip()) and right.strip() != ""


def _try_parse_remote_token(
    piece: str,
    *,
    allow_create: bool,
    current_ws: str | None,
    option: str,
) -> Target | None:
    text = piece.strip()
    if not text:
        return None

    if ":" in text:
        workspace_raw, item_raw = text.split(":", 1)
        workspace_raw = workspace_raw.strip()
        item_raw = item_raw.strip()
        if not _is_guid(workspace_raw):
            return None
        workspace_id = _parse_guid(workspace_raw, what="workspace id")
        if not item_raw:
            if not allow_create:
                raise ParseError(
                    f"{option} requires workspace:artifact; "
                    f"missing artifact id on '{piece}'"
                )
            return Target(workspace_id=workspace_id, item_id=None)
        if item_raw == "*":
            return Target(workspace_id=workspace_id, item_id=None, wildcard=True)
        if not _is_guid(item_raw):
            return None
        return Target(
            workspace_id=workspace_id,
            item_id=_parse_guid(item_raw, what="artifact id"),
        )

    if current_ws is not None and _is_guid(text):
        return Target(
            workspace_id=current_ws,
            item_id=_parse_guid(text, what="artifact id"),
        )

    if _is_guid(text):
        if not allow_create:
            raise ParseError(
                f"{option} requires workspace:artifact; got '{piece}' "
                "(workspace only is not allowed)"
            )
        return Target(
            workspace_id=_parse_guid(text, what="workspace id"),
            item_id=None,
        )

    return None


def _expand_scoped_targets(
    raw: str,
    *,
    allow_create: bool,
    option: str,
) -> list[Target]:
    """Expand one flag value with optional workspace shorthand for bare GUIDs."""
    remotes, paths = _classify_one_flag_value(
        raw, option=option, allow_create=allow_create
    )
    if paths:
        raise ParseError(
            f"{option} expected remote selector(s); got local path(s): "
            f"{', '.join(str(p) for p in paths)}"
        )
    return remotes


def _validate_single_workspace_overwrite(targets: list[Target], *, option: str) -> None:
    if any(not t.is_create for t in targets):
        workspaces = {t.workspace_id for t in targets}
        if len(workspaces) > 1:
            raise ParseError(
                f"one {option} value may only refer to one workspace for "
                f"overwrite targets; got {len(workspaces)}: "
                + ", ".join(sorted(workspaces))
                + ". Use separate flags per workspace."
            )


def _is_guid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


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
