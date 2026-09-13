"""Multi-kind pack (.ftdep schema v3) orchestration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

from fabric_tools.colours import FG_OK
from fabric_tools.exit_codes import EXIT_OK, EXIT_USER
from fabric_tools.guid_map import GuidMapError, guid_map_confirm_line, resolve_guid_maps
from fabric_tools.manifest import (
    KIND_DATAFLOW,
    KIND_DATAFLOW_GEN1,
    KIND_NOTEBOOK,
    KIND_ORG_APP,
    KIND_PAGINATED_REPORT,
    KIND_PIPELINE,
    KIND_REPORT,
    KIND_SEMANTIC_MODEL,
    KIND_UDF,
    REMAP_KINDS,
    DeploymentManifest,
    ManifestEntry,
    ManifestError,
    entry_guid_maps_from_manifest,
    group_pack_entries_by_kind,
    load_manifest,
    resolve_manifest_path,
)
from fabric_tools.parsing import CommandMode


def run_pack_command(
    mode: CommandMode,
    *,
    manifest: str,
    silent: bool = False,
    dry_run: bool = False,
    remap_values: list[str] | None = None,
    publish: bool = False,
    include_schedules: bool = False,
    independent: bool = False,
) -> None:
    """Load a v3 pack and dispatch ordered kind groups to existing runners."""
    from fabric_tools.cli import (
        _enforce_readonly_command,
        _exit_error,
        run_dataflow_command,
        run_dataflow_gen1_command,
        run_notebook_command,
        run_org_app_command,
        run_paginated_report_command,
        run_pipeline_command,
        run_report_command,
        run_semantic_model_command,
        run_udf_command,
    )

    _enforce_readonly_command(mode, dry_run=dry_run)

    if remap_values and mode is not CommandMode.DEPLOY:
        _exit_error("--remap / -r is only valid with deploy")
    if publish and mode is not CommandMode.DEPLOY:
        _exit_error("--publish / -p is only valid with deploy")
    if include_schedules and mode not in {
        CommandMode.DOWNLOAD,
        CommandMode.DEPLOY,
        CommandMode.COMPARE,
    }:
        _exit_error(
            "--include-schedules / -i is only valid with download/deploy/compare"
        )
    if independent and mode not in {
        CommandMode.DOWNLOAD,
        CommandMode.DEPLOY,
        CommandMode.COMPARE,
    }:
        _exit_error("--independent / -i is only valid with download/deploy/compare")

    try:
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
    except ManifestError as exc:
        _exit_error(str(exc))

    reverse = mode is CommandMode.DELETE
    groups = group_pack_entries_by_kind(loaded.entries, reverse=reverse)

    pack_guid_maps: list[dict[str, str] | None] | None = None
    if mode is CommandMode.DEPLOY:
        try:
            pack_guid_maps = _resolve_pack_guid_maps(loaded, remap_values)
        except (GuidMapError, ManifestError) as exc:
            _exit_error(str(exc))
        if dry_run and any(pack_guid_maps or []):
            line = guid_map_confirm_line(
                entry_guid_maps_from_manifest(loaded) if not remap_values else []
            )
            if remap_values:
                typer.secho(
                    "remap ok: CLI --remap / -r overrides pack remap path refs",
                    fg=FG_OK,
                )
            elif line:
                typer.secho(f"remap ok: {line}", fg=FG_OK)

    runners: dict[str, Callable[..., None]] = {
        KIND_NOTEBOOK: run_notebook_command,
        KIND_DATAFLOW: run_dataflow_command,
        KIND_DATAFLOW_GEN1: run_dataflow_gen1_command,
        KIND_ORG_APP: run_org_app_command,
        KIND_PIPELINE: run_pipeline_command,
        KIND_UDF: run_udf_command,
        KIND_SEMANTIC_MODEL: run_semantic_model_command,
        KIND_REPORT: run_report_command,
        KIND_PAGINATED_REPORT: run_paginated_report_command,
    }

    failed = False
    for kind, entries in groups:
        runner = runners.get(kind)
        if runner is None:
            _exit_error(f"unsupported pack entry kind '{kind}'")

        try:
            target_values, file_values, origin_values, names = _entry_cli_args(
                entries, mode=mode
            )
        except ManifestError as exc:
            _exit_error(str(exc))

        group_maps = None
        if (
            mode is CommandMode.DEPLOY
            and kind in REMAP_KINDS
            and pack_guid_maps is not None
        ):
            group_maps = _slice_guid_maps_for_group(loaded, entries, pack_guid_maps)

        typer.secho(
            f"pack {mode.value}: {kind} ({len(entries)} entr"
            f"{'y' if len(entries) == 1 else 'ies'})",
            fg=FG_OK,
        )

        kwargs: dict[str, Any] = {
            "target_values": target_values,
            "file_values": file_values,
            "origin_values": origin_values,
            "silent": silent,
            "dry_run": dry_run,
            "names": names,
            "manifest": None,
        }
        if kind in REMAP_KINDS:
            kwargs["guid_maps_override"] = group_maps
        if kind == KIND_DATAFLOW and mode is CommandMode.DEPLOY:
            kwargs["publish"] = publish
        if kind == KIND_PIPELINE:
            kwargs["include_schedules"] = include_schedules
        if kind == KIND_REPORT and mode in {
            CommandMode.DOWNLOAD,
            CommandMode.DEPLOY,
            CommandMode.COMPARE,
        }:
            kwargs["independent"] = independent

        try:
            runner(mode, **kwargs)
        except typer.Exit as exc:
            code = int(exc.exit_code or 0)
            if code != EXIT_OK:
                failed = True
                break

    raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)


def _resolve_pack_guid_maps(
    manifest: DeploymentManifest,
    remap_values: list[str] | None,
) -> list[dict[str, str] | None]:
    """Per-declaration-index GUID maps (CLI ``-r`` overrides pack/entry paths)."""
    if remap_values:
        remappable_indices = [
            index
            for index, entry in enumerate(manifest.entries)
            if entry.kind in REMAP_KINDS
        ]
        if not remappable_indices:
            raise ManifestError(
                "--remap / -r was set but this pack has no remappable entries "
                f"({', '.join(sorted(REMAP_KINDS))})"
            )
        specs = resolve_guid_maps(remap_values, len(remappable_indices))
        maps: list[dict[str, str] | None] = [None] * len(manifest.entries)
        for entry_index, spec in zip(remappable_indices, specs, strict=True):
            maps[entry_index] = spec.mapping if spec is not None else None
        return maps
    specs = entry_guid_maps_from_manifest(manifest)
    return [spec.mapping if spec is not None else None for spec in specs]


def _slice_guid_maps_for_group(
    manifest: DeploymentManifest,
    entries: list[ManifestEntry],
    pack_maps: list[dict[str, str] | None],
) -> list[dict[str, str] | None]:
    index_by_id = {id(entry): index for index, entry in enumerate(manifest.entries)}
    return [pack_maps[index_by_id[id(entry)]] for entry in entries]


def _entry_cli_args(
    entries: list[ManifestEntry],
    *,
    mode: CommandMode,
) -> tuple[list[str], list[str] | None, list[str] | None, list[str | None] | None]:
    targets: list[str] = []
    files: list[str] = []
    origins: list[str] = []
    names: list[str | None] = []
    for entry in entries:
        if entry.item_id:
            targets.append(f"{entry.workspace_id}:{entry.item_id}")
        else:
            targets.append(entry.workspace_id)
        if mode is CommandMode.DELETE:
            continue
        if entry.has_file:
            assert entry.file is not None
            files.append(str(entry.file))
        elif entry.has_origin:
            origins.append(f"{entry.origin_workspace_id}:{entry.origin_item_id}")
        names.append(entry.display_name)

    if mode is CommandMode.DELETE:
        return targets, None, None, None
    if files and origins:
        raise ManifestError("pack group mixes file and origin entries")
    if not files and not origins:
        raise ManifestError("pack group entries need file or origin")
    return (
        targets,
        files or None,
        origins or None,
        names if any(names) else None,
    )
