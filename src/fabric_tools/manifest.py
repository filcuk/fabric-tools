"""Deployment manifest (.ftdep) load/save helpers (schema v3 packs)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fabric_tools.guid_map import GuidMapError, GuidMapSpec, load_guid_map
from fabric_tools.parsing import Target, WorkItem

SCHEMA_VERSION_V3 = 3
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION_V3})
MANIFEST_SUFFIX = ".ftdep"

KIND_PACK = "pack"
KIND_NOTEBOOK = "notebook"
KIND_DATAFLOW = "dataflow"
KIND_DATAFLOW_GEN1 = "dataflow-gen1"
KIND_PIPELINE = "pipeline"
KIND_UDF = "udf"
KIND_REPORT = "report"
KIND_PAGINATED_REPORT = "paginated-report"
KIND_SEMANTIC_MODEL = "semantic-model"

ITEM_KINDS = frozenset(
    {
        KIND_NOTEBOOK,
        KIND_DATAFLOW,
        KIND_DATAFLOW_GEN1,
        KIND_PIPELINE,
        KIND_UDF,
        KIND_REPORT,
        KIND_PAGINATED_REPORT,
        KIND_SEMANTIC_MODEL,
    }
)

# Kinds that honour remap path refs / CLI --remap.
REMAP_KINDS = frozenset({KIND_NOTEBOOK, KIND_DATAFLOW, KIND_PIPELINE, KIND_UDF})

# Deploy order: models before reports; other kinds after (stable within kind).
DEPLOY_KIND_ORDER: tuple[str, ...] = (
    KIND_SEMANTIC_MODEL,
    KIND_REPORT,
    KIND_NOTEBOOK,
    KIND_UDF,
    KIND_DATAFLOW,
    KIND_DATAFLOW_GEN1,
    KIND_PIPELINE,
    KIND_PAGINATED_REPORT,
)

_DEPLOY_KIND_RANK = {kind: index for index, kind in enumerate(DEPLOY_KIND_ORDER)}


class ManifestError(ValueError):
    """Invalid or unusable deployment manifest."""


@dataclass(frozen=True)
class ManifestEntry:
    kind: str
    workspace_id: str
    file: Path | None = None
    item_id: str | None = None
    display_name: str | None = None
    origin_workspace_id: str | None = None
    origin_item_id: str | None = None
    # Optional bound semantic model id for report entries (joined create/download).
    semantic_model_id: str | None = None
    # Optional GUID remap JSON path (resolved absolute), relative in JSON.
    remap: Path | None = None

    @property
    def has_file(self) -> bool:
        return self.file is not None

    @property
    def has_origin(self) -> bool:
        return self.origin_workspace_id is not None and self.origin_item_id is not None


@dataclass(frozen=True)
class DeploymentManifest:
    kind: str
    entries: tuple[ManifestEntry, ...]
    schema_version: int = SCHEMA_VERSION_V3
    # Optional pack-default GUID remap JSON path (resolved absolute).
    remap: Path | None = None


def resolve_manifest_path(value: str | Path) -> Path:
    """Resolve a ``-m`` value to a ``.ftdep`` path (does not require the file to exist)."""
    text = str(value).strip()
    if not text:
        raise ManifestError("manifest path/stem is empty")
    path = Path(text)
    if path.suffix.lower() != MANIFEST_SUFFIX:
        path = path.with_name(path.name + MANIFEST_SUFFIX)
    return path


def resolve_inspect_target(value: str | Path) -> Path:
    """Resolve ``manifest inspect -m``: existing directory, else a ``.ftdep`` path."""
    text = str(value).strip()
    if not text:
        raise ManifestError("manifest path/stem is empty")
    path = Path(text)
    if path.is_dir():
        return path
    return resolve_manifest_path(path)


def load_manifest(path: str | Path) -> DeploymentManifest:
    """Load and validate a schema v3 pack ``.ftdep`` JSON file."""
    resolved = Path(path)
    if not resolved.is_file():
        raise ManifestError(f"manifest not found: {resolved}")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"failed to read manifest {resolved}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be a JSON object: {resolved}")

    schema_version = raw.get("schemaVersion")
    if schema_version is None:
        raise ManifestError(
            f"manifest missing schemaVersion in {resolved} "
            f"(required: {SCHEMA_VERSION_V3}; schemaVersion 1/2 are unsupported — "
            "rewrite as a v3 pack)"
        )
    if not isinstance(schema_version, int):
        raise ManifestError(f"invalid schemaVersion in {resolved}")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ManifestError(
            f"unsupported schemaVersion {schema_version} in {resolved} "
            f"(supported: {SCHEMA_VERSION_V3} only; schemaVersion 1/2 are "
            "unsupported — rewrite as a v3 pack with kind 'pack')"
        )

    kind = raw.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise ManifestError(f"manifest missing kind: {resolved}")
    kind = kind.strip()
    if kind != KIND_PACK:
        raise ManifestError(
            f"manifest kind must be '{KIND_PACK}' in {resolved} "
            f"(got '{kind}'); rewrite as a v3 pack"
        )

    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise ManifestError(
            f"manifest must contain a non-empty entries array: {resolved}"
        )

    base = resolved.parent
    pack_remap = _parse_optional_path(
        raw.get("remap"),
        base=base,
        field="remap",
        path=resolved,
    )
    entries: list[ManifestEntry] = []
    for index, item in enumerate(entries_raw):
        entries.append(_parse_entry(item, base=base, index=index, path=resolved))

    return DeploymentManifest(
        kind=KIND_PACK,
        entries=tuple(entries),
        schema_version=schema_version,
        remap=pack_remap,
    )


def save_manifest(path: str | Path, manifest: DeploymentManifest) -> tuple[Path, bool]:
    """Write *manifest* as JSON if content differs from the existing file.

    Returns ``(path, written)``. *written* is False when the file already
    matches the serialized payload (no disk write).
    """
    resolved = resolve_manifest_path(path)
    if not manifest.entries:
        raise ManifestError("cannot save manifest with no entries")
    if manifest.kind != KIND_PACK:
        raise ManifestError(
            f"cannot save manifest kind '{manifest.kind}'; must be pack"
        )
    if manifest.schema_version != SCHEMA_VERSION_V3:
        raise ManifestError(
            f"cannot save schemaVersion {manifest.schema_version}; "
            f"must be {SCHEMA_VERSION_V3}"
        )

    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION_V3,
        "kind": KIND_PACK,
        "entries": [
            _entry_to_json(entry, base=resolved.parent) for entry in manifest.entries
        ],
    }
    if manifest.remap is not None:
        payload["remap"] = _path_to_stored(manifest.remap, base=resolved.parent)

    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if resolved.is_file():
        try:
            if resolved.read_text(encoding="utf-8") == text:
                return resolved, False
        except OSError as exc:
            raise ManifestError(f"failed to read manifest {resolved}: {exc}") from exc
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"failed to write manifest {resolved}: {exc}") from exc
    return resolved, True


def work_items_from_manifest(
    manifest: DeploymentManifest,
    *,
    expected_kind: str = KIND_NOTEBOOK,
) -> tuple[list[WorkItem], list[str | None]]:
    """Convert homogeneous pack entries to work items and optional display names.

    Requires a v3 pack whose every entry ``kind`` matches *expected_kind*.
    Mixed packs must use ``fabric-tools pack …``.
    """
    _require_pack(manifest)
    _require_homogeneous_kind(manifest, expected_kind)

    items: list[WorkItem] = []
    names: list[str | None] = []
    for entry in manifest.entries:
        target = Target(workspace_id=entry.workspace_id, item_id=entry.item_id)
        origin: Target | None = None
        if entry.has_origin:
            assert entry.origin_workspace_id is not None
            assert entry.origin_item_id is not None
            origin = Target(
                workspace_id=entry.origin_workspace_id,
                item_id=entry.origin_item_id,
            )
        items.append(WorkItem(target=target, file=entry.file, origin=origin))
        names.append(entry.display_name)
    return items, names


def delete_targets_from_manifest(
    manifest: DeploymentManifest,
    *,
    expected_kind: str,
) -> list[WorkItem]:
    """Load delete work items from a homogeneous pack (each entry must have ``itemId``).

    File/origin fields on entries are ignored. Does not rewrite the manifest.
    """
    _require_pack(manifest)
    _require_homogeneous_kind(manifest, expected_kind)
    items: list[WorkItem] = []
    missing: list[str] = []
    for index, entry in enumerate(manifest.entries, start=1):
        if entry.item_id is None:
            missing.append(f"entries[{index - 1}] workspaceId={entry.workspace_id}")
            continue
        items.append(
            WorkItem(
                Target(workspace_id=entry.workspace_id, item_id=entry.item_id),
                None,
            )
        )
    if missing:
        raise ManifestError(
            "delete via --manifest requires itemId on every entry; missing on: "
            + ", ".join(missing)
        )
    return items


def manifest_from_work_items(
    items: Sequence[WorkItem],
    *,
    kind: str = KIND_NOTEBOOK,
    display_names: Sequence[str | None] | None = None,
    item_id_overrides: Sequence[str | None] | None = None,
    semantic_model_id_overrides: Sequence[str | None] | None = None,
    remap: Path | str | None = None,
    entry_remaps: Sequence[Path | str | None] | None = None,
) -> DeploymentManifest:
    """Build a v3 pack manifest from effective work items (one entry kind).

    *item_id_overrides* (e.g. create-deploy results) replaces ``None`` item ids
    when the override at the same index is set.

    *semantic_model_id_overrides* sets optional ``semanticModelId`` on report entries.

    *remap* is an optional pack-level GUID remap path; *entry_remaps* overrides
    per entry (same length as items when provided).
    """
    if not items:
        raise ManifestError("cannot build manifest from empty work item list")
    if kind not in ITEM_KINDS:
        raise ManifestError(f"unknown entry kind '{kind}'")

    names = list(display_names) if display_names is not None else [None] * len(items)
    if len(names) == 1 and len(items) > 1:
        names = names * len(items)
    if len(names) != len(items):
        raise ManifestError(
            f"display name count ({len(names)}) must be 1 or match work items "
            f"({len(items)})"
        )

    overrides = (
        list(item_id_overrides)
        if item_id_overrides is not None
        else [None] * len(items)
    )
    if len(overrides) != len(items):
        raise ManifestError(
            f"item_id override count ({len(overrides)}) must match work items "
            f"({len(items)})"
        )

    sm_overrides = (
        list(semantic_model_id_overrides)
        if semantic_model_id_overrides is not None
        else [None] * len(items)
    )
    if len(sm_overrides) != len(items):
        raise ManifestError(
            f"semantic_model_id override count ({len(sm_overrides)}) must match "
            f"work items ({len(items)})"
        )

    remaps = list(entry_remaps) if entry_remaps is not None else [None] * len(items)
    if len(remaps) != len(items):
        raise ManifestError(
            f"entry remap count ({len(remaps)}) must match work items ({len(items)})"
        )

    pack_remap = Path(remap).resolve() if remap is not None and remap != "" else None

    entries: list[ManifestEntry] = []
    for item, name, override_id, sm_id, entry_remap in zip(
        items, names, overrides, sm_overrides, remaps, strict=True
    ):
        if item.target is None:
            raise ManifestError("manifest entry requires a target")
        if item.file is None and item.origin is None:
            raise ManifestError("manifest entry requires a local file or origin")
        if item.file is not None and item.origin is not None:
            raise ManifestError("manifest entry cannot have both file and origin")
        item_id = override_id if override_id else item.target.item_id
        origin_ws = None
        origin_item = None
        if item.origin is not None:
            if item.origin.item_id is None:
                raise ManifestError("manifest origin requires workspace:artifact")
            origin_ws = item.origin.workspace_id
            origin_item = item.origin.item_id
        entry_remap_path = (
            Path(entry_remap).resolve()
            if entry_remap is not None and entry_remap != ""
            else None
        )
        entries.append(
            ManifestEntry(
                kind=kind,
                workspace_id=item.target.workspace_id,
                item_id=item_id,
                file=item.file,
                display_name=name,
                origin_workspace_id=origin_ws,
                origin_item_id=origin_item,
                semantic_model_id=sm_id,
                remap=entry_remap_path,
            )
        )

    return DeploymentManifest(
        kind=KIND_PACK,
        entries=tuple(entries),
        schema_version=SCHEMA_VERSION_V3,
        remap=pack_remap,
    )


def effective_remap_path(
    manifest: DeploymentManifest,
    entry: ManifestEntry,
) -> Path | None:
    """Resolve the GUID remap path for *entry* (entry wins over pack default)."""
    if entry.remap is not None:
        return entry.remap
    return manifest.remap


def entry_guid_maps_from_manifest(
    manifest: DeploymentManifest,
    *,
    expected_kind: str | None = None,
) -> list[GuidMapSpec | None]:
    """Load per-entry GUID maps from pack/entry remap path refs.

    When *expected_kind* is set, requires a homogeneous pack of that kind.
    Missing or invalid remap files raise ``ManifestError``.
    """
    _require_pack(manifest)
    entries = list(manifest.entries)
    if expected_kind is not None:
        _require_homogeneous_kind(manifest, expected_kind)

    specs: list[GuidMapSpec | None] = []
    for index, entry in enumerate(entries):
        path = effective_remap_path(manifest, entry)
        if path is None or entry.kind not in REMAP_KINDS:
            specs.append(None)
            continue
        try:
            mapping = load_guid_map(path)
        except GuidMapError as exc:
            raise ManifestError(
                f"entries[{index}] remap failed ({path}): {exc}"
            ) from exc
        specs.append(GuidMapSpec(path=path, mapping=mapping))
    return specs


def order_pack_entries(
    entries: Sequence[ManifestEntry],
    *,
    reverse: bool = False,
) -> list[ManifestEntry]:
    """Order pack entries for deploy (or reverse for delete).

    Kind priority is stable; within a kind, original declaration order is kept.
    """
    ranked = list(enumerate(entries))
    ranked.sort(
        key=lambda pair: (
            _DEPLOY_KIND_RANK.get(pair[1].kind, len(DEPLOY_KIND_ORDER)),
            pair[0],
        ),
        reverse=False,
    )
    ordered = [entry for _, entry in ranked]
    if reverse:
        # Reverse kind groups while keeping declaration order within each kind.
        groups: list[list[ManifestEntry]] = []
        for entry in ordered:
            if groups and groups[-1][0].kind == entry.kind:
                groups[-1].append(entry)
            else:
                groups.append([entry])
        ordered = [entry for group in reversed(groups) for entry in group]
    return ordered


def group_pack_entries_by_kind(
    entries: Sequence[ManifestEntry],
    *,
    reverse: bool = False,
) -> list[tuple[str, list[ManifestEntry]]]:
    """Order then group contiguous same-kind entries for pack orchestration."""
    ordered = order_pack_entries(entries, reverse=reverse)
    groups: list[tuple[str, list[ManifestEntry]]] = []
    for entry in ordered:
        if groups and groups[-1][0] == entry.kind:
            groups[-1][1].append(entry)
        else:
            groups.append((entry.kind, [entry]))
    return groups


def item_id_overrides_from_results(
    results: Sequence[Any],
) -> list[str | None]:
    """Extract per-index item ids from operation results (``OpResult``-like)."""
    overrides: list[str | None] = []
    for result in results:
        ok = bool(getattr(result, "ok", False))
        item_id = getattr(result, "item_id", None)
        overrides.append(str(item_id) if ok and item_id else None)
    return overrides


def semantic_model_id_overrides_from_results(
    results: Sequence[Any],
) -> list[str | None]:
    """Extract per-index ``semantic_model_id`` from report-like operation results."""
    overrides: list[str | None] = []
    for result in results:
        ok = bool(getattr(result, "ok", False))
        sm_id = getattr(result, "semantic_model_id", None)
        overrides.append(str(sm_id) if ok and sm_id else None)
    return overrides


def semantic_model_ids_from_manifest(
    manifest: DeploymentManifest,
) -> list[str | None]:
    """Return per-entry ``semanticModelId`` values from a loaded manifest."""
    return [entry.semantic_model_id for entry in manifest.entries]


def list_manifest_paths(directory: str | Path | None = None) -> list[Path]:
    """Return ``*.ftdep`` files in *directory* (default: cwd), sorted by name."""
    root = Path.cwd() if directory is None else Path(directory)
    if not root.is_dir():
        raise ManifestError(f"directory not found: {root}")
    return sorted(
        (
            p
            for p in root.iterdir()
            if p.is_file() and p.suffix.lower() == MANIFEST_SUFFIX
        ),
        key=lambda p: p.name.lower(),
    )


def delete_manifest_file(path: str | Path) -> Path:
    """Unlink an existing ``.ftdep`` file. Caller must confirm."""
    resolved = resolve_manifest_path(path)
    if not resolved.is_file():
        raise ManifestError(f"manifest not found: {resolved}")
    try:
        resolved.unlink()
    except OSError as exc:
        raise ManifestError(f"failed to delete manifest {resolved}: {exc}") from exc
    return resolved


def move_manifest_file(
    source: str | Path, destination: str | Path
) -> tuple[Path, Path]:
    """Move an existing ``.ftdep`` to *destination* (creates parent dirs).

    Caller must confirm. Destination is a file path, not a drop-in directory.
    """
    src = resolve_manifest_path(source)
    dst = resolve_manifest_path(destination)
    if not src.is_file():
        raise ManifestError(f"manifest not found: {src}")
    if src.resolve() == dst.resolve():
        raise ManifestError("source and destination are the same path")
    if dst.is_dir():
        raise ManifestError(f"destination is a directory: {dst}")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file():
            dst.unlink()
        shutil.move(str(src), str(dst))
    except OSError as exc:
        raise ManifestError(f"failed to move manifest {src} to {dst}: {exc}") from exc
    return src, dst


def format_inspect_line(manifest: DeploymentManifest, *, path: Path) -> str:
    """One-line summary for listing manifests in a directory."""
    kinds = sorted({entry.kind for entry in manifest.entries})
    kind_part = ",".join(kinds) if kinds else "?"
    remap_part = (
        " remap" if manifest.remap or any(e.remap for e in manifest.entries) else ""
    )
    return (
        f"{path.name}  kind={manifest.kind}[{kind_part}]  "
        f"schemaVersion={manifest.schema_version}  "
        f"entries={len(manifest.entries)}{remap_part}"
    )


def format_inspect(manifest: DeploymentManifest, *, path: Path | None = None) -> str:
    """Human-readable summary for ``fabric-tools manifest inspect``."""
    lines: list[str] = []
    if path is not None:
        lines.append(f"manifest: {path}")
    lines.append(f"schemaVersion: {manifest.schema_version}")
    lines.append(f"kind: {manifest.kind}")
    if manifest.remap is not None:
        lines.append(f"remap: {manifest.remap}")
    lines.append(f"entries: {len(manifest.entries)}")
    for index, entry in enumerate(manifest.entries, start=1):
        target = (
            f"{entry.workspace_id}:{entry.item_id}"
            if entry.item_id
            else f"{entry.workspace_id} (create)"
        )
        name_part = f", name={entry.display_name!r}" if entry.display_name else ""
        sm_part = (
            f", semanticModelId={entry.semantic_model_id}"
            if entry.semantic_model_id
            else ""
        )
        remap_part = f", remap={entry.remap}" if entry.remap is not None else ""
        if entry.has_origin:
            source = f"{entry.origin_workspace_id}:{entry.origin_item_id}"
        else:
            source = str(entry.file)
        lines.append(
            f"  {index}. [{entry.kind}] {target} <- {source}"
            f"{name_part}{sm_part}{remap_part}"
        )
    return "\n".join(lines)


def _require_pack(manifest: DeploymentManifest) -> None:
    if manifest.kind != KIND_PACK or manifest.schema_version != SCHEMA_VERSION_V3:
        raise ManifestError(
            f"manifest kind is '{manifest.kind}' "
            f"(schemaVersion={manifest.schema_version}); expected pack schema "
            f"{SCHEMA_VERSION_V3}"
        )


def _require_homogeneous_kind(
    manifest: DeploymentManifest,
    expected_kind: str,
) -> None:
    kinds = {entry.kind for entry in manifest.entries}
    if kinds != {expected_kind}:
        found = ", ".join(sorted(kinds))
        raise ManifestError(
            f"manifest pack entry kinds are [{found}], expected all "
            f"'{expected_kind}' for this command (use 'fabric-tools pack …' "
            "for mixed packs)"
        )


def _parse_optional_path(
    raw: Any,
    *,
    base: Path,
    field: str,
    path: Path,
    index: int | None = None,
) -> Path | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        where = f"entries[{index}].{field}" if index is not None else field
        raise ManifestError(f"{where} must be a string or omitted in {path}")
    text = raw.strip()
    if not text:
        return None
    file_path = Path(text)
    if not file_path.is_absolute():
        return (base / file_path).resolve()
    return file_path.resolve()


def _parse_entry(
    raw: Any,
    *,
    base: Path,
    index: int,
    path: Path,
) -> ManifestEntry:
    if not isinstance(raw, dict):
        raise ManifestError(f"entries[{index}] must be an object in {path}")

    kind_raw = raw.get("kind")
    if not isinstance(kind_raw, str) or not kind_raw.strip():
        raise ManifestError(f"entries[{index}].kind is required in {path}")
    kind = kind_raw.strip()
    if kind not in ITEM_KINDS:
        raise ManifestError(
            f"entries[{index}].kind '{kind}' is not a supported item kind in {path}"
        )

    workspace_id = raw.get("workspaceId")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ManifestError(f"entries[{index}].workspaceId is required in {path}")

    item_raw = raw.get("itemId", None)
    if item_raw is None or item_raw == "":
        item_id = None
    elif isinstance(item_raw, str):
        item_id = item_raw.strip() or None
    else:
        raise ManifestError(
            f"entries[{index}].itemId must be a string or null in {path}"
        )

    file_raw = raw.get("file")
    origin_ws_raw = raw.get("originWorkspaceId")
    origin_item_raw = raw.get("originItemId")

    file_path: Path | None = None
    origin_workspace_id: str | None = None
    origin_item_id: str | None = None

    has_file = isinstance(file_raw, str) and bool(file_raw.strip())
    has_origin_ws = isinstance(origin_ws_raw, str) and bool(origin_ws_raw.strip())
    has_origin_item = isinstance(origin_item_raw, str) and bool(origin_item_raw.strip())

    if has_file and (has_origin_ws or has_origin_item):
        raise ManifestError(
            f"entries[{index}] must use either file or origin, not both in {path}"
        )
    if not has_file and not (has_origin_ws and has_origin_item):
        raise ManifestError(
            f"entries[{index}] requires file or originWorkspaceId+originItemId "
            f"in {path}"
        )
    if has_origin_ws != has_origin_item:
        raise ManifestError(
            f"entries[{index}] originWorkspaceId and originItemId must both be set "
            f"in {path}"
        )

    if has_file:
        file_path = Path(file_raw)  # type: ignore[arg-type]
        if not file_path.is_absolute():
            file_path = (base / file_path).resolve()
        else:
            file_path = file_path.resolve()

    if has_origin_ws and has_origin_item:
        origin_workspace_id = str(origin_ws_raw).strip()
        origin_item_id = str(origin_item_raw).strip()

    display_name = raw.get("displayName")
    if display_name is not None and not isinstance(display_name, str):
        raise ManifestError(
            f"entries[{index}].displayName must be a string or omitted in {path}"
        )
    if isinstance(display_name, str):
        display_name = display_name.strip() or None

    sm_raw = raw.get("semanticModelId", None)
    if sm_raw is None or sm_raw == "":
        semantic_model_id = None
    elif isinstance(sm_raw, str):
        semantic_model_id = sm_raw.strip() or None
    else:
        raise ManifestError(
            f"entries[{index}].semanticModelId must be a string or null in {path}"
        )

    remap = _parse_optional_path(
        raw.get("remap"),
        base=base,
        field="remap",
        path=path,
        index=index,
    )

    return ManifestEntry(
        kind=kind,
        workspace_id=workspace_id.strip(),
        item_id=item_id,
        file=file_path,
        display_name=display_name,
        origin_workspace_id=origin_workspace_id,
        origin_item_id=origin_item_id,
        semantic_model_id=semantic_model_id,
        remap=remap,
    )


def _path_to_stored(path: Path, *, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _entry_to_json(entry: ManifestEntry, *, base: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": entry.kind,
        "workspaceId": entry.workspace_id,
        "itemId": entry.item_id,
    }
    if entry.has_file:
        assert entry.file is not None
        payload["file"] = _path_to_stored(entry.file, base=base)
    if entry.has_origin:
        payload["originWorkspaceId"] = entry.origin_workspace_id
        payload["originItemId"] = entry.origin_item_id
    if entry.display_name:
        payload["displayName"] = entry.display_name
    if entry.semantic_model_id:
        payload["semanticModelId"] = entry.semantic_model_id
    if entry.remap is not None:
        payload["remap"] = _path_to_stored(entry.remap, base=base)
    return payload
