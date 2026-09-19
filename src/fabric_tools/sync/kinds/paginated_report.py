"""Orchestration for paginated report sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_PAGINATED_REPORT
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _resolve_paginated_report_deploy_names,
    _resolve_paginated_report_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_paginated_report_command(
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
    """Shared entry for paginated-report CLI commands and the interactive wizard."""
    from fabric_tools.confirm import (
        confirm_delete_paginated_report,
        confirm_deploy_actions_paginated_report,
        confirm_download_overwrites_paginated_report,
        resolve_paginated_report_download_files,
    )
    from fabric_tools.paginated_report.compare import (
        run_compare_batch as run_pr_compare,
    )
    from fabric_tools.paginated_report.ops import run_delete_batch as run_pr_delete
    from fabric_tools.paginated_report.ops import run_deploy_batch as run_pr_deploy
    from fabric_tools.paginated_report.ops import run_download_batch as run_pr_download
    from fabric_tools.powerbi_client import PowerBiClient
    from fabric_tools.validate import run_dry_run_paginated_report

    spec = KindSpec(
        kind=KIND_PAGINATED_REPORT,
        status_label="paginated-report",
        make_client=PowerBiClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_paginated_report_inputs),
        resolve_deploy_names=_resolve_paginated_report_deploy_names,
        run_dry_run=run_dry_run_paginated_report,
        resolve_download_files=resolve_paginated_report_download_files,
        confirm_download=confirm_download_overwrites_paginated_report,
        confirm_deploy=confirm_deploy_actions_paginated_report,
        confirm_delete=confirm_delete_paginated_report,
        run_download=run_pr_download,
        run_deploy=run_pr_deploy,
        run_compare=run_pr_compare,
        run_delete=run_pr_delete,
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
