"""Typer commands: report."""

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
    silent_opt,
    target_opt,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import run_report_command

report_app = typer.Typer(
    name="report",
    help="Fabric report items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)

_INDEPENDENT_HELP = option_help(
    "Report-only: do not join/download/deploy a packable semantic model."
)


@report_app.command("download")
def report_download(
    origin: list[str] | None = origin_opt(help=ORIGIN_DOWNLOAD_HELP),
    target: list[str] | None = target_opt(help=TARGET_DOWNLOAD_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DOWNLOAD_HELP),
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help=_INDEPENDENT_HELP,
    ),
) -> None:
    """Download report(s) from Fabric (joined model by default when packable)."""
    run_report_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
        independent=independent,
    )


@report_app.command("deploy")
def report_deploy(
    target: list[str] | None = target_opt(help=TARGET_DEPLOY_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_DEPLOY_HELP),
    name: list[str] | None = name_opt(),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DEPLOY_HELP),
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help=_INDEPENDENT_HELP,
    ),
) -> None:
    """Deploy report(s) (create or overwrite; joined model by default)."""
    run_report_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        names=name,
        manifest=manifest,
        independent=independent,
    )


@report_app.command("compare")
def report_compare(
    target: list[str] | None = target_opt(help=TARGET_COMPARE_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_COMPARE_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_COMPARE_HELP),
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help=_INDEPENDENT_HELP,
    ),
) -> None:
    """Compare local/remote report folders to remote targets (not .pbix)."""
    run_report_command(
        CommandMode.COMPARE,
        target_values=target,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
        independent=independent,
    )


@report_app.command("delete")
def report_delete(
    target: list[str] | None = target_opt(help=TARGET_DELETE_HELP),
    manifest: str | None = manifest_opt(help=MANIFEST_DELETE_HELP),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DELETE_HELP),
) -> None:
    """Delete report(s) only (upstream model left intact when known)."""
    run_report_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
