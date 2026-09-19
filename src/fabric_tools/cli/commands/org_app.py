"""Typer commands: org_app."""

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
    origin_opt,
    silent_opt,
    target_opt,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import run_org_app_command

org_app_app = typer.Typer(
    name="org-app",
    help="Fabric Org App items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@org_app_app.command("download")
def org_app_download(
    origin: list[str] | None = origin_opt(help=ORIGIN_DOWNLOAD_HELP),
    target: list[str] | None = target_opt(help=TARGET_DOWNLOAD_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DOWNLOAD_HELP),
) -> None:
    """Download Org App definition(s) from Fabric to local folders."""
    run_org_app_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@org_app_app.command("deploy")
def org_app_deploy(
    target: list[str] | None = target_opt(help=TARGET_DEPLOY_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_DEPLOY_HELP),
    name: list[str] | None = name_opt(),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DEPLOY_HELP),
) -> None:
    """Deploy Org App definition(s) (create or overwrite)."""
    run_org_app_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        names=name,
        manifest=manifest,
    )


@org_app_app.command("compare")
def org_app_compare(
    target: list[str] | None = target_opt(help=TARGET_COMPARE_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_COMPARE_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_COMPARE_HELP),
) -> None:
    """Compare local/remote Org App definitions to remote targets."""
    run_org_app_command(
        CommandMode.COMPARE,
        target_values=target,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@org_app_app.command("delete")
def org_app_delete(
    target: list[str] | None = target_opt(help=TARGET_DELETE_HELP),
    manifest: str | None = manifest_opt(help=MANIFEST_DELETE_HELP),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DELETE_HELP),
) -> None:
    """Soft-delete Org App item(s) in Fabric."""
    run_org_app_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
