"""Orchestration for Org App sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_ORG_APP
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _resolve_org_app_deploy_names,
    _resolve_org_app_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_org_app_command(
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
    """Shared entry for Org App CLI commands and the interactive wizard."""
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_org_app,
        confirm_deploy_actions_org_app,
        confirm_download_overwrites_org_app,
        resolve_org_app_download_files,
    )
    from fabric_tools.org_app.compare import run_compare_batch as run_org_compare
    from fabric_tools.org_app.ops import run_delete_batch as run_org_delete
    from fabric_tools.org_app.ops import run_deploy_batch as run_org_deploy
    from fabric_tools.org_app.ops import run_download_batch as run_org_download
    from fabric_tools.validate import run_dry_run_org_app

    spec = KindSpec(
        kind=KIND_ORG_APP,
        status_label="org-app",
        make_client=FabricClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_org_app_inputs),
        resolve_deploy_names=_resolve_org_app_deploy_names,
        run_dry_run=run_dry_run_org_app,
        resolve_download_files=resolve_org_app_download_files,
        confirm_download=confirm_download_overwrites_org_app,
        confirm_deploy=confirm_deploy_actions_org_app,
        confirm_delete=confirm_delete_org_app,
        run_download=run_org_download,
        run_deploy=run_org_deploy,
        run_compare=run_org_compare,
        run_delete=run_org_delete,
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
