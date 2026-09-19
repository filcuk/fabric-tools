"""Orchestration for Dataflow Gen1 sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_DATAFLOW_GEN1
from fabric_tools.parsing import CommandMode, ParseError, WorkItem
from fabric_tools.sync.common import (
    _resolve_dataflow_gen1_deploy_names,
    _resolve_dataflow_gen1_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_dataflow_gen1_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    name_filter: str | None = None,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for dataflow-gen1 CLI commands and the interactive wizard."""
    from fabric_tools.confirm import (
        confirm_delete_dataflow_gen1,
        confirm_deploy_create_dataflow_gen1,
        confirm_download_overwrites_dataflow_gen1,
        resolve_dataflow_gen1_download_files,
    )
    from fabric_tools.dataflow_gen1.compare import run_compare_batch as run_df_compare
    from fabric_tools.dataflow_gen1.definition import (
        DefinitionError as DataflowDefinitionError,
    )
    from fabric_tools.dataflow_gen1.ops import run_delete_batch as run_df_delete
    from fabric_tools.dataflow_gen1.ops import run_deploy_batch as run_df_deploy
    from fabric_tools.dataflow_gen1.ops import run_download_batch as run_df_download
    from fabric_tools.powerbi_client import PowerBiClient
    from fabric_tools.validate import run_dry_run_dataflow_gen1

    def resolve_deploy_names(
        items: list[WorkItem],
        resolved: list[str | None] | list[str] | None,
    ) -> list[str]:
        try:
            return _resolve_dataflow_gen1_deploy_names(items, resolved)
        except DataflowDefinitionError as exc:
            raise ParseError(str(exc)) from exc

    spec = KindSpec(
        kind=KIND_DATAFLOW_GEN1,
        status_label="dataflow-gen1",
        make_client=PowerBiClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_dataflow_gen1_inputs),
        resolve_deploy_names=resolve_deploy_names,
        run_dry_run=run_dry_run_dataflow_gen1,
        resolve_download_files=resolve_dataflow_gen1_download_files,
        confirm_download=confirm_download_overwrites_dataflow_gen1,
        confirm_deploy=confirm_deploy_create_dataflow_gen1,
        confirm_delete=confirm_delete_dataflow_gen1,
        run_download=run_df_download,
        run_deploy=run_df_deploy,
        run_compare=run_df_compare,
        run_delete=run_df_delete,
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
        ),
    )
