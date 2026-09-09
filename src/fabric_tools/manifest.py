"""Deployment manifest (.ftdep) load/save helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from fabric_tools.parsing import Target, WorkItem

SCHEMA_VERSION_V1 = 1
SCHEMA_VERSION_V2 = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION_V1, SCHEMA_VERSION_V2})
MANIFEST_SUFFIX = ".ftdep"
KIND_NOTEBOOK = "notebook"


class ManifestError(ValueError):
    """Invalid or unusable deployment manifest."""


@dataclass(frozen=True)
class ManifestEntry:
    workspace_id: str
    file: Path | None = None
    item_id: str | None = None
    display_name: str | None = None
    origin_workspace_id: str | None = None
    origin_item_id: str | None = None

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
    schema_version: int = SCHEMA_VERSION_V1


def resolve_manifest_path(value: str | Path) -> Path:
    """Resolve a ``-m`` value to a ``.ftdep`` path (does not require the file to exist)."""
    text = str(value).strip()
    if not text:
        raise ManifestError("manifest path/stem is empty")
    path = Path(text)
    if path.suffix.lower() != MANIFEST_SUFFIX:
        path = path.with_name(path.name + MANIFEST_SUFFIX)
    return path


def load_manifest(path: str | Path) -> DeploymentManifest:
    """Load and validate a ``.ftdep`` JSON file."""
    resolved = Path(path)
    if not resolved.is_file():
        raise ManifestError(f"manifest not found: {resolved}")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"failed to read manifest {resolved}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be a JSON object: {resolved}")

    schema_version = raw.get("schemaVersion", SCHEMA_VERSION_V1)
    if not isinstance(schema_version, int):
        raise ManifestError(f"invalid schemaVersion in {resolved}")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ManifestError(
            f"unsupported schemaVersion {schema_version} in {resolved} "
            f"(supported: {', '.join(str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS))})"
        )

    kind = raw.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise ManifestError(f"manifest missing kind: {resolved}")

    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise ManifestError(f"manifest must contain a non-empty entries array: {resolved}")

    base = resolved.parent
    entries: list[ManifestEntry] = []
    for index, item in enumerate(entries_raw):
        entries.append(
            _parse_entry(
                item,
                base=base,
                index=index,
                path=resolved,
                schema_version=schema_version,
            )
        )

    return DeploymentManifest(
        kind=kind.strip(),
        entries=tuple(entries),
        schema_version=schema_version,
    )


def save_manifest(path: str | Path, manifest: DeploymentManifest) -> Path:
    """Write *manifest* as JSON; returns the path written."""
    resolved = resolve_manifest_path(path)
    if not manifest.entries:
        raise ManifestError("cannot save manifest with no entries")

    payload: dict[str, Any] = {
        "schemaVersion": manifest.schema_version,
        "kind": manifest.kind,
        "entries": [
            _entry_to_json(entry, base=resolved.parent) for entry in manifest.entries
        ],
    }
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ManifestError(f"failed to write manifest {resolved}: {exc}") from exc
    return resolved


def work_items_from_manifest(
    manifest: DeploymentManifest,
    *,
    expected_kind: str = KIND_NOTEBOOK,
) -> tuple[list[WorkItem], list[str | None]]:
    """Convert notebook manifest entries to work items and optional display names.

    Raises ``ManifestError`` if ``manifest.kind`` does not match *expected_kind*.
    """
    if manifest.kind != expected_kind:
        raise ManifestError(
            f"manifest kind is '{manifest.kind}', expected '{expected_kind}' "
            "for this command"
        )

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


def manifest_from_work_items(
    items: Sequence[WorkItem],
    *,
    kind: str = KIND_NOTEBOOK,
    display_names: Sequence[str | None] | None = None,
    item_id_overrides: Sequence[str | None] | None = None,
) -> DeploymentManifest:
    """Build a manifest from effective work items.

    *item_id_overrides* (e.g. create-deploy results) replaces ``None`` item ids
    when the override at the same index is set.

    Writes schemaVersion 2 when any entry uses a Fabric origin; otherwise v1.
    """
    if not items:
        raise ManifestError("cannot build manifest from empty work item list")

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

    entries: list[ManifestEntry] = []
    uses_origin = False
    for item, name, override_id in zip(items, names, overrides, strict=True):
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
            uses_origin = True
            origin_ws = item.origin.workspace_id
            origin_item = item.origin.item_id
        entries.append(
            ManifestEntry(
                workspace_id=item.target.workspace_id,
                item_id=item_id,
                file=item.file,
                display_name=name,
                origin_workspace_id=origin_ws,
                origin_item_id=origin_item,
            )
        )

    schema_version = SCHEMA_VERSION_V2 if uses_origin else SCHEMA_VERSION_V1
    return DeploymentManifest(
        kind=kind,
        entries=tuple(entries),
        schema_version=schema_version,
    )


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


def list_manifest_paths(directory: str | Path | None = None) -> list[Path]:
    """Return ``*.ftdep`` files in *directory* (default: cwd), sorted by name."""
    root = Path.cwd() if directory is None else Path(directory)
    if not root.is_dir():
        raise ManifestError(f"directory not found: {root}")
    return sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix.lower() == MANIFEST_SUFFIX),
        key=lambda p: p.name.lower(),
    )


def format_inspect_line(manifest: DeploymentManifest, *, path: Path) -> str:
    """One-line summary for listing manifests in a directory."""
    return (
        f"{path.name}  kind={manifest.kind}  "
        f"schemaVersion={manifest.schema_version}  entries={len(manifest.entries)}"
    )


def format_inspect(manifest: DeploymentManifest, *, path: Path | None = None) -> str:
    """Human-readable summary for ``fabric-tools inspect``."""
    lines: list[str] = []
    if path is not None:
        lines.append(f"manifest: {path}")
    lines.append(f"schemaVersion: {manifest.schema_version}")
    lines.append(f"kind: {manifest.kind}")
    lines.append(f"entries: {len(manifest.entries)}")
    for index, entry in enumerate(manifest.entries, start=1):
        target = (
            f"{entry.workspace_id}:{entry.item_id}"
            if entry.item_id
            else f"{entry.workspace_id} (create)"
        )
        name_part = f", name={entry.display_name!r}" if entry.display_name else ""
        if entry.has_origin:
            source = f"{entry.origin_workspace_id}:{entry.origin_item_id}"
        else:
            source = str(entry.file)
        lines.append(f"  {index}. {target} <- {source}{name_part}")
    return "\n".join(lines)


def _parse_entry(
    raw: Any,
    *,
    base: Path,
    index: int,
    path: Path,
    schema_version: int,
) -> ManifestEntry:
    if not isinstance(raw, dict):
        raise ManifestError(f"entries[{index}] must be an object in {path}")

    workspace_id = raw.get("workspaceId")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ManifestError(f"entries[{index}].workspaceId is required in {path}")

    item_raw = raw.get("itemId", None)
    if item_raw is None or item_raw == "":
        item_id = None
    elif isinstance(item_raw, str):
        item_id = item_raw.strip() or None
    else:
        raise ManifestError(f"entries[{index}].itemId must be a string or null in {path}")

    file_raw = raw.get("file")
    origin_ws_raw = raw.get("originWorkspaceId")
    origin_item_raw = raw.get("originItemId")

    file_path: Path | None = None
    origin_workspace_id: str | None = None
    origin_item_id: str | None = None

    has_file = isinstance(file_raw, str) and bool(file_raw.strip())
    has_origin_ws = isinstance(origin_ws_raw, str) and bool(origin_ws_raw.strip())
    has_origin_item = isinstance(origin_item_raw, str) and bool(origin_item_raw.strip())

    if schema_version == SCHEMA_VERSION_V1:
        if not has_file:
            raise ManifestError(f"entries[{index}].file is required in {path}")
        if has_origin_ws or has_origin_item:
            raise ManifestError(
                f"entries[{index}] origin fields require schemaVersion 2 in {path}"
            )
    else:
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

    return ManifestEntry(
        workspace_id=workspace_id.strip(),
        item_id=item_id,
        file=file_path,
        display_name=display_name,
        origin_workspace_id=origin_workspace_id,
        origin_item_id=origin_item_id,
    )


def _entry_to_json(entry: ManifestEntry, *, base: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workspaceId": entry.workspace_id,
        "itemId": entry.item_id,
    }
    if entry.has_file:
        assert entry.file is not None
        try:
            stored = entry.file.resolve().relative_to(base.resolve())
            file_value = stored.as_posix()
        except ValueError:
            file_value = str(entry.file.resolve())
        payload["file"] = file_value
    if entry.has_origin:
        payload["originWorkspaceId"] = entry.origin_workspace_id
        payload["originItemId"] = entry.origin_item_id
    if entry.display_name:
        payload["displayName"] = entry.display_name
    return payload
