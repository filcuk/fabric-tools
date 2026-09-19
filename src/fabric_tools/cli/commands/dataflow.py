"""Typer commands: dataflow."""

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
    run_dataflow_command,
)

dataflow_app = typer.Typer(
    name="dataflow",
    help="Fabric Dataflow Gen2 items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@dataflow_app.command("download")
def dataflow_download(
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
) -> None:
    """Download Dataflow Gen2 definition(s) from Fabric to local folders."""
    run_dataflow_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@dataflow_app.command("deploy")
def dataflow_deploy(
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
    remap: list[str] | None = typer.Option(
        None,
        "--remap",
        "-r",
        help=GUID_REMAP_HELP,
    ),
    publish: bool = typer.Option(
        False,
        "--publish",
        "-p",
        help="(optional) After successful create/update, run Fabric Apply Changes "
        "(prepare for refresh; same preparation as UI Save). User identity only.",
    ),
) -> None:
    """Deploy Dataflow Gen2 item(s) from local folders or a Fabric origin."""
    run_dataflow_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        names=name,
        manifest=manifest,
        remap_values=remap,
        publish=publish,
    )


@dataflow_app.command("compare")
def dataflow_compare(
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
) -> None:
    """Compare target Dataflow Gen2 to a local folder or Fabric origin."""
    run_dataflow_command(
        CommandMode.COMPARE,
        target_values=target,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )


@dataflow_app.command("delete")
def dataflow_delete(
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
    """Soft-delete Dataflow Gen2 item(s) in Fabric."""
    run_dataflow_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
