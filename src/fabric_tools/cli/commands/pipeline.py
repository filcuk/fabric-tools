"""Typer commands: pipeline."""

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
    TARGET_DEPLOY_HELP,
    TARGET_DOWNLOAD_HELP,
    dry_run_opt,
    filter_opt,
    manifest_opt,
    name_opt,
    option_help,
    origin_opt,
    remap_opt,
    silent_opt,
    target_opt,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import run_pipeline_command

pipeline_app = typer.Typer(
    name="pipeline",
    help="Fabric DataPipeline items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)

_INCLUDE_SCHEDULES_DOWNLOAD = option_help(
    "Include .schedules in the downloaded folder. "
    "Default download also removes a leftover local .schedules file."
)
_INCLUDE_SCHEDULES_DEPLOY = option_help(
    "Sync .schedules from the source. Default is pipeline-only: "
    "omit source .schedules; overwrite without this flag reattaches each "
    "target's existing .schedules."
)
_INCLUDE_SCHEDULES_COMPARE = option_help(
    "Include .schedules in the unified diff. "
    "Default compares pipeline-content.json only (.platform always excluded)."
)


@pipeline_app.command("download")
def pipeline_download(
    origin: list[str] | None = origin_opt(help=ORIGIN_DOWNLOAD_HELP),
    target: list[str] | None = target_opt(help=TARGET_DOWNLOAD_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DOWNLOAD_HELP),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help=_INCLUDE_SCHEDULES_DOWNLOAD,
    ),
) -> None:
    """Download DataPipeline definition(s) from Fabric to local folders."""
    run_pipeline_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
        include_schedules=include_schedules,
    )


@pipeline_app.command("deploy")
def pipeline_deploy(
    target: list[str] | None = target_opt(help=TARGET_DEPLOY_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_DEPLOY_HELP),
    name: list[str] | None = name_opt(),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DEPLOY_HELP),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help=_INCLUDE_SCHEDULES_DEPLOY,
    ),
    remap: list[str] | None = remap_opt(),
) -> None:
    """Deploy DataPipeline definition(s) (create or overwrite)."""
    run_pipeline_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        names=name,
        manifest=manifest,
        include_schedules=include_schedules,
        remap_values=remap,
    )


@pipeline_app.command("compare")
def pipeline_compare(
    target: list[str] | None = target_opt(help=TARGET_COMPARE_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_COMPARE_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_COMPARE_HELP),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help=_INCLUDE_SCHEDULES_COMPARE,
    ),
) -> None:
    """Compare local/remote DataPipeline definitions to remote targets."""
    run_pipeline_command(
        CommandMode.COMPARE,
        target_values=target,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
        include_schedules=include_schedules,
    )


@pipeline_app.command("delete")
def pipeline_delete(
    target: list[str] | None = target_opt(help=TARGET_DELETE_HELP),
    manifest: str | None = manifest_opt(help=MANIFEST_DELETE_HELP),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DELETE_HELP),
) -> None:
    """Soft-delete DataPipeline item(s) in Fabric."""
    run_pipeline_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
