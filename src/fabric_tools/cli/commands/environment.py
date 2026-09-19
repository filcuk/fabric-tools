"""Typer commands: environment."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    FILTER_HELP,
    HELP_CONTEXT,
    MANIFEST_HELP,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import (
    run_environment_command,
)

environment_app = typer.Typer(
    name="environment",
    help="Fabric Environment items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@environment_app.command("download")
def environment_download(
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Remote workspace:artifact to download. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(optional) Local destination path. "
        "Defaults to remote display name with the kind extension in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One path may broadcast to all origins.",
    ),
    manifest: str | None = typer.Option(None, "--manifest", "-m", help=MANIFEST_HELP),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False, "--silent", "-s", help="(optional) Skip confirmation prompts."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or files only; do not download.",
    ),
) -> None:
    """Download Environment definition(s) from Fabric to local folders."""
    run_environment_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@environment_app.command("deploy")
def environment_deploy(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Fabric workspace:artifact source. "
        "Repeatable or comma-separated; one origin may broadcast to all targets.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to folder stem "
        "or origin display name.",
    ),
    manifest: str | None = typer.Option(None, "--manifest", "-m", help=MANIFEST_HELP),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False, "--silent", "-s", help="(optional) Skip confirmation prompts."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or sources only; do not deploy.",
    ),
) -> None:
    """Deploy Environment item(s) from local folders or a Fabric origin."""
    run_environment_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        names=name,
        manifest=manifest,
    )


@environment_app.command("compare")
def environment_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Must 1:1 match --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Fabric workspace:artifact to compare "
        "against --target. Must 1:1 match --target.",
    ),
    manifest: str | None = typer.Option(None, "--manifest", "-m", help=MANIFEST_HELP),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or sources only; do not compare.",
    ),
) -> None:
    """Compare target Environment to a local folder or Fabric origin."""
    run_environment_command(
        CommandMode.COMPARE,
        target_values=target,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@environment_app.command("delete")
def environment_delete(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated.",
    ),
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help="(optional) Load workspace:artifact targets from a .ftdep "
        "(entries must have itemId). Not rewritten after delete.",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False, "--silent", "-s", help="(optional) Skip confirmation prompts."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets only; do not delete.",
    ),
) -> None:
    """Soft-delete Environment item(s) in Fabric."""
    run_environment_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
