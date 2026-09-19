"""Typer commands: report."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    FILTER_HELP,
    HELP_CONTEXT,
    MANIFEST_HELP,
)
from fabric_tools.parsing import CommandMode
from fabric_tools.sync import (
    run_report_command,
)

report_app = typer.Typer(
    name="report",
    help="Fabric report items.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@report_app.command("download")
def report_download(
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
        help="(optional) Validate targets and/or local paths only; do not download.",
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help="(optional) Download the report only (no joined semantic model / "
        "LiveConnect for .pbix).",
    ),
) -> None:
    """Download report definition(s) to local *.Report folders or .pbix files."""
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
        help="(required without -m or -d) Local path or remote workspace:artifact source.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional) Display name for create. Defaults from folder/.pbix stem. "
        "One name may broadcast.",
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
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help="(optional) Deploy the report only (no joined model). "
        "Errors on thick .pbix or packable sibling *.SemanticModel.",
    ),
) -> None:
    """Create or overwrite report(s); joins a packable semantic model by default."""
    run_report_command(
        CommandMode.DEPLOY,
        target_values=target,
        origin_values=origin,
        names=name,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
        independent=independent,
    )


@report_app.command("compare")
def report_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(required without -m or -d) Local path or remote workspace:artifact source.",
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
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help="(optional) Compare the report definition only (skip joined semantic model).",
    ),
) -> None:
    """Compare target report to a local *.Report folder or Fabric origin."""
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
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
        help="(optional) Validate targets only; do not delete.",
    ),
) -> None:
    """Soft-delete report(s); the bound semantic model is left intact."""
    run_report_command(
        CommandMode.DELETE,
        target_values=target,
        silent=silent,
        dry_run=dry_run,
        name_filter=name_filter,
        manifest=manifest,
    )
