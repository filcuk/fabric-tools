"""Orchestration for Variable Library sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_VARIABLE_LIBRARY
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _resolve_variable_library_deploy_names,
    _resolve_variable_library_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_variable_library_command(
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
    """Shared entry for Variable Library commands and the interactive wizard."""
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_variable_library,
        confirm_deploy_actions_variable_library,
        confirm_download_overwrites_variable_library,
        resolve_variable_library_download_files,
    )
    from fabric_tools.validate import run_dry_run_variable_library
    from fabric_tools.variable_library.compare import (
        run_compare_batch as run_variable_library_compare,
    )
    from fabric_tools.variable_library.ops import (
        run_delete_batch as run_variable_library_delete,
    )
    from fabric_tools.variable_library.ops import (
        run_deploy_batch as run_variable_library_deploy,
    )
    from fabric_tools.variable_library.ops import (
        run_download_batch as run_variable_library_download,
    )

    spec = KindSpec(
        kind=KIND_VARIABLE_LIBRARY,
        status_label="variable-library",
        make_client=FabricClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_variable_library_inputs),
        resolve_deploy_names=_resolve_variable_library_deploy_names,
        run_dry_run=run_dry_run_variable_library,
        resolve_download_files=resolve_variable_library_download_files,
        confirm_download=confirm_download_overwrites_variable_library,
        confirm_deploy=confirm_deploy_actions_variable_library,
        confirm_delete=confirm_delete_variable_library,
        run_download=run_variable_library_download,
        run_deploy=run_variable_library_deploy,
        run_compare=run_variable_library_compare,
        run_delete=run_variable_library_delete,
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
