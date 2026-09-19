"""Orchestration for notebook sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_NOTEBOOK, ManifestError
from fabric_tools.notebook.cells import CellSelectionError
from fabric_tools.parsing import CommandMode, ParseError
from fabric_tools.sync.common import _resolve_deploy_names, _resolve_notebook_inputs
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    remap_dry_run_notes,
    require_remap_deploy_only,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_notebook_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    name_filter: str | None = None,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    cells: list[str] | None = None,
    ignore_outputs: bool = False,
    manifest: str | None = None,
    remap_values: list[str] | None = None,
    guid_maps_override: list[dict[str, str] | None] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry used by CLI commands and the interactive wizard.

    *on_success* is called after a completed successful operation or dry-run (all
    checks/ops/compare results ok), before the process exit code is raised — used
    by interactive mode to offer saving a deployment manifest.
    """
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_actions,
        confirm_deploy_actions,
        confirm_download_overwrites,
        resolve_notebook_download_files,
    )
    from fabric_tools.notebook.cells import parse_cell_indices, validate_cells_usage
    from fabric_tools.notebook.compare import run_compare_batch
    from fabric_tools.notebook.ops import (
        run_delete_batch,
        run_deploy_batch,
        run_download_batch,
    )
    from fabric_tools.validate import run_dry_run

    def after_resolve(req: SyncRequest) -> None:
        cell_indices = parse_cell_indices(cells)
        validate_cells_usage(req.mode, req.items, cell_indices, dry_run=req.dry_run)
        req.extras["cell_indices"] = cell_indices

    def dry_run_kwargs(req: SyncRequest) -> dict:
        return {"cell_indices": req.extras.get("cell_indices")}

    def deploy_confirm_kwargs(req: SyncRequest) -> dict:
        return {
            "cell_indices": req.extras.get("cell_indices"),
            "guid_map_line": req.map_line,
        }

    def deploy_kwargs(req: SyncRequest) -> dict:
        return {
            "cell_indices": req.extras.get("cell_indices"),
            "guid_maps": req.guid_maps or None,
        }

    def compare_kwargs(_req: SyncRequest) -> dict:
        return {"ignore_outputs": ignore_outputs}

    spec = KindSpec(
        kind=KIND_NOTEBOOK,
        status_label="notebook",
        make_client=FabricClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_notebook_inputs),
        resolve_deploy_names=_resolve_deploy_names,
        run_dry_run=run_dry_run,
        resolve_download_files=resolve_notebook_download_files,
        confirm_download=confirm_download_overwrites,
        confirm_deploy=confirm_deploy_actions,
        confirm_delete=confirm_delete_actions,
        run_download=run_download_batch,
        run_deploy=run_deploy_batch,
        run_compare=run_compare_batch,
        run_delete=run_delete_batch,
        supports_remap=True,
        parse_exceptions=(ParseError, ManifestError, CellSelectionError),
        validate_flags=require_remap_deploy_only,
        after_resolve=after_resolve,
        dry_run_notes=remap_dry_run_notes,
        dry_run_kwargs=dry_run_kwargs,
        deploy_confirm_kwargs=deploy_confirm_kwargs,
        deploy_kwargs=deploy_kwargs,
        compare_kwargs=compare_kwargs,
    )
    run_sync_command(
        spec,
        SyncRequest(
            mode=mode,
            target_values=target_values,
            silent=silent,
            dry_run=dry_run,
            name_filter=name_filter,
            origin_values=origin_values,
            names=names,
            manifest=manifest,
            on_success=on_success,
            remap_values=remap_values,
            guid_maps_override=guid_maps_override,
        ),
    )
