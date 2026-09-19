"""Typer commands: pack."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    GUID_REMAP_HELP,
    HELP_CONTEXT,
)
from fabric_tools.parsing import CommandMode

pack_app = typer.Typer(
    name="pack",
    help="Multi-kind deployment packs (.ftdep schema v3).",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@pack_app.command("download")
def pack_download(
    manifest: str = typer.Option(
        ...,
        "--manifest",
        "-m",
        help="Pack manifest stem or path (.ftdep schema v3).",
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
        help="(optional) Validate only; do not download.",
    ),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Include pipeline .schedules when present in the pack.",
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        help="(optional) Report-only (do not join semantic model).",
    ),
) -> None:
    """Download all items in a multi-kind pack (ordered by kind)."""
    from fabric_tools.pack_run import run_pack_command

    run_pack_command(
        CommandMode.DOWNLOAD,
        manifest=manifest,
        silent=silent,
        dry_run=dry_run,
        include_schedules=include_schedules,
        independent=independent,
    )


@pack_app.command("deploy")
def pack_deploy(
    manifest: str = typer.Option(
        ...,
        "--manifest",
        "-m",
        help="Pack manifest stem or path (.ftdep schema v3).",
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
        help="(optional) Validate only; do not deploy.",
    ),
    remap: list[str] | None = typer.Option(
        None,
        "--remap",
        "-r",
        help=GUID_REMAP_HELP + " Overrides pack/entry remap path refs for this run.",
    ),
    publish: bool = typer.Option(
        False,
        "--publish",
        "-p",
        help="(optional) After dataflow create/update, run Apply Changes.",
    ),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Include pipeline .schedules when present in the pack.",
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        help="(optional) Report-only (do not join semantic model).",
    ),
) -> None:
    """Deploy all items in a multi-kind pack (models before reports)."""
    from fabric_tools.pack_run import run_pack_command

    run_pack_command(
        CommandMode.DEPLOY,
        manifest=manifest,
        silent=silent,
        dry_run=dry_run,
        remap_values=remap,
        publish=publish,
        include_schedules=include_schedules,
        independent=independent,
    )


@pack_app.command("compare")
def pack_compare(
    manifest: str = typer.Option(
        ...,
        "--manifest",
        "-m",
        help="Pack manifest stem or path (.ftdep schema v3).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate only; do not compare.",
    ),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Include pipeline .schedules when present in the pack.",
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        help="(optional) Report-only (do not join semantic model).",
    ),
) -> None:
    """Compare all items in a multi-kind pack."""
    from fabric_tools.pack_run import run_pack_command

    run_pack_command(
        CommandMode.COMPARE,
        manifest=manifest,
        silent=True,
        dry_run=dry_run,
        include_schedules=include_schedules,
        independent=independent,
    )


@pack_app.command("delete")
def pack_delete(
    manifest: str = typer.Option(
        ...,
        "--manifest",
        "-m",
        help="Pack manifest stem or path (.ftdep schema v3).",
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
        help="(optional) Validate only; do not delete.",
    ),
) -> None:
    """Delete all items in a multi-kind pack (reports before models)."""
    from fabric_tools.pack_run import run_pack_command

    run_pack_command(
        CommandMode.DELETE,
        manifest=manifest,
        silent=silent,
        dry_run=dry_run,
    )
