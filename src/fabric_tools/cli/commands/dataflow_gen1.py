"""Typer commands: dataflow_gen1."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    DRY_RUN_COMPARE_HELP,
    DRY_RUN_DELETE_HELP,
    DRY_RUN_DEPLOY_HELP,
    DRY_RUN_DOWNLOAD_HELP,
    HELP_CONTEXT,
    MANIFEST_DELETE_HELP,
    ORIGIN_COMPARE_HELP,
    ORIGIN_DEPLOY_HELP,
    ORIGIN_DOWNLOAD_HELP,
    TARGET_COMPARE_HELP,
    TARGET_DELETE_HELP,
    TARGET_DOWNLOAD_HELP,
    conditional_required_help,
    dry_run_opt,
    filter_opt,
    manifest_opt,
    name_opt,
    option_help,
    origin_opt,
    silent_opt,
    target_opt,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import run_dataflow_gen1_command

dataflow_gen1_app = typer.Typer(
    name="dataflow-gen1",
    help="Power BI Dataflow Gen1 items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)

_TARGET_DEPLOY_GEN1 = conditional_required_help(
    "workspace GUID (create only). "
    "Repeatable or comma-separated (spaces after commas OK)."
)
_NAME_DEPLOY_GEN1 = option_help(
    "Display name written into model.json before import. "
    "Defaults to file stem or origin display name."
)


@dataflow_gen1_app.command("download")
def dataflow_gen1_download(
    origin: list[str] | None = origin_opt(help=ORIGIN_DOWNLOAD_HELP),
    target: list[str] | None = target_opt(help=TARGET_DOWNLOAD_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DOWNLOAD_HELP),
) -> None:
    """Download Dataflow Gen1 model.json from Power BI."""
    run_dataflow_gen1_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@dataflow_gen1_app.command("deploy")
def dataflow_gen1_deploy(
    target: list[str] | None = target_opt(help=_TARGET_DEPLOY_GEN1),
    origin: list[str] | None = origin_opt(help=ORIGIN_DEPLOY_HELP),
    name: list[str] | None = name_opt(help=_NAME_DEPLOY_GEN1),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DEPLOY_HELP),
) -> None:
    """Create Dataflow Gen1 in Power BI (create only; no overwrite)."""
    run_dataflow_gen1_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        names=name,
        manifest=manifest,
    )


@dataflow_gen1_app.command("compare")
def dataflow_gen1_compare(
    target: list[str] | None = target_opt(help=TARGET_COMPARE_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_COMPARE_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_COMPARE_HELP),
) -> None:
    """Compare local/remote Dataflow Gen1 definitions to remote targets."""
    run_dataflow_gen1_command(
        CommandMode.COMPARE,
        target_values=target,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@dataflow_gen1_app.command("delete")
def dataflow_gen1_delete(
    target: list[str] | None = target_opt(help=TARGET_DELETE_HELP),
    manifest: str | None = manifest_opt(help=MANIFEST_DELETE_HELP),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DELETE_HELP),
) -> None:
    """Delete Dataflow Gen1 item(s) in Power BI."""
    run_dataflow_gen1_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
