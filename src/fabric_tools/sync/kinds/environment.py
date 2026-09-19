"""Orchestration for Environment sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_ENVIRONMENT
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _resolve_environment_deploy_names,
    _resolve_environment_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_environment_command(
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
    """Shared entry for Environment CLI commands and the interactive wizard."""
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_environment,
        confirm_deploy_actions_environment,
        confirm_download_overwrites_environment,
        resolve_environment_download_files,
    )
    from fabric_tools.environment.compare import (
        run_compare_batch as run_environment_compare,
    )
    from fabric_tools.environment.ops import run_delete_batch as run_environment_delete
    from fabric_tools.environment.ops import run_deploy_batch as run_environment_deploy
    from fabric_tools.environment.ops import (
        run_download_batch as run_environment_download,
    )
    from fabric_tools.validate import run_dry_run_environment

    spec = KindSpec(
        kind=KIND_ENVIRONMENT,
        status_label="environment",
        make_client=FabricClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_environment_inputs),
        resolve_deploy_names=_resolve_environment_deploy_names,
        run_dry_run=run_dry_run_environment,
        resolve_download_files=resolve_environment_download_files,
        confirm_download=confirm_download_overwrites_environment,
        confirm_deploy=confirm_deploy_actions_environment,
        confirm_delete=confirm_delete_environment,
        run_download=run_environment_download,
        run_deploy=run_environment_deploy,
        run_compare=run_environment_compare,
        run_delete=run_environment_delete,
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
