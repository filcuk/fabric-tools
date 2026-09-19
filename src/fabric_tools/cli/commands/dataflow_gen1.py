"""Typer commands: dataflow_gen1."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    FILTER_HELP,
    HELP_CONTEXT,
    MANIFEST_HELP,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import (
    run_dataflow_gen1_command,
)

dataflow_gen1_app = typer.Typer(
    name="dataflow-gen1",
    help="Power BI Dataflow Gen1 items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@dataflow_gen1_app.command("download")
def dataflow_gen1_download(
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
    """Download Dataflow Gen1 model.json from Power BI to local files."""
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create only). "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Overwrite (workspace:artifact) is not supported.",
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
        help="(optional) Display name written into model.json before import. "
        "Defaults to the model name (or origin name).",
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
) -> None:
    """Create Dataflow Gen1 item(s) from local model.json or a remote origin."""
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
    """Compare target Dataflow Gen1 to a local model.json or remote origin."""
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
    """Delete Dataflow Gen1 item(s) via the Power BI API."""
    run_dataflow_gen1_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
