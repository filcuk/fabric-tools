"""Typer commands: notebook."""

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
    remap_opt,
    silent_opt,
    target_opt,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import run_notebook_command

notebook_app = typer.Typer(
    name="notebook",
    help="Fabric notebooks.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@notebook_app.command("download")
def notebook_download(
    origin: list[str] | None = origin_opt(help=ORIGIN_DOWNLOAD_HELP),
    target: list[str] | None = target_opt(help=TARGET_DOWNLOAD_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DOWNLOAD_HELP),
) -> None:
    """Download notebook(s) from Fabric to local files."""
    run_notebook_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@notebook_app.command("deploy")
def notebook_deploy(
    target: list[str] | None = target_opt(help=TARGET_DEPLOY_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_DEPLOY_HELP),
    name: list[str] | None = name_opt(),
    cells: list[str] | None = typer.Option(
        None,
        "--cells",
        "-c",
        help=(
            "(optional, overwrite .ipynb only) 1-based cell indices to replace "
            "(e.g. 1,3,5 or 1, 3, 5). Single notebook only; whole cells including outputs. "
            "Requires a local --origin .ipynb (not a remote origin)."
        ),
    ),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DEPLOY_HELP),
    remap: list[str] | None = remap_opt(),
) -> None:
    """Deploy notebook(s) from local files or a Fabric origin (create or overwrite)."""
    run_notebook_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        names=name,
        cells=cells,
        manifest=manifest,
        remap_values=remap,
    )


@notebook_app.command("compare")
def notebook_compare(
    target: list[str] | None = target_opt(help=TARGET_COMPARE_HELP),
    origin: list[str] | None = origin_opt(help=ORIGIN_COMPARE_HELP),
    manifest: str | None = manifest_opt(),
    name_filter: str | None = filter_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_COMPARE_HELP),
    include_outputs: bool = typer.Option(
        True,
        "--include-outputs",
        "-i",
        help="(optional) For .ipynb diffs, include cell outputs.",
    ),
) -> None:
    """Compare local/remote notebooks to remote targets."""
    run_notebook_command(
        CommandMode.COMPARE,
        target_values=target,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        name_filter=name_filter,
        ignore_outputs=not include_outputs,
        manifest=manifest,
    )


@notebook_app.command("delete")
def notebook_delete(
    target: list[str] | None = target_opt(help=TARGET_DELETE_HELP),
    manifest: str | None = manifest_opt(help=MANIFEST_DELETE_HELP),
    name_filter: str | None = filter_opt(),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=DRY_RUN_DELETE_HELP),
) -> None:
    """Soft-delete notebook(s) in Fabric."""
    run_notebook_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
