"""Typer commands: pipeline."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    FILTER_HELP,
    GUID_REMAP_HELP,
    HELP_CONTEXT,
    MANIFEST_HELP,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import (
    run_pipeline_command,
)

pipeline_app = typer.Typer(
    name="pipeline",
    help="Fabric DataPipeline items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@pipeline_app.command("download")
def pipeline_download(
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
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help=MANIFEST_HELP,
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or files only; do not download.",
    ),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Include .schedules in the downloaded folder. "
        "Default omits .schedules and removes a leftover local .schedules.",
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated "
        "(spaces after commas OK).",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Local path or remote workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to folder stem "
        "or origin display name.",
    ),
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help=MANIFEST_HELP,
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or sources only; do not deploy.",
    ),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Sync .schedules from the source. Default is pipeline-only: "
        "create omits .schedules; overwrite reattaches the target's existing "
        ".schedules so remote schedules stay untouched.",
    ),
    remap: list[str] | None = typer.Option(
        None,
        "--remap",
        "-r",
        help=GUID_REMAP_HELP,
    ),
) -> None:
    """Deploy DataPipeline item(s) from local folders or a Fabric origin."""
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "With a local --origin path: one workspace only. Must 1:1 match --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Local path or remote workspace:artifact to compare against --target. Must 1:1 match --target (no broadcast).",
    ),
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help=MANIFEST_HELP,
    ),
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
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Include .schedules in the unified diff. "
        "Default compares pipeline content only.",
    ),
) -> None:
    """Compare target DataPipeline to a local folder or Fabric origin."""
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
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
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets only; do not delete.",
    ),
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
