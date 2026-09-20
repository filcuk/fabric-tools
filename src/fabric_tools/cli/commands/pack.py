"""Typer commands: pack."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    GUID_REMAP_HELP,
    HELP_CONTEXT,
    dry_run_opt,
    manifest_opt,
    option_help,
    remap_opt,
    silent_opt,
)
from fabric_tools.parsing import CommandMode

pack_app = typer.Typer(
    name="pack",
    help="Multi-kind deployment packs (.ftdep schema v3).",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)

_PACK_MANIFEST = option_help("Pack manifest stem or path (.ftdep schema v3).")
_INCLUDE_SCHEDULES_HELP = option_help(
    "Include pipeline .schedules when present in the pack."
)
_INDEPENDENT_HELP = option_help("Report-only (do not join semantic model).")


@pack_app.command("download")
def pack_download(
    manifest: str = manifest_opt(help=_PACK_MANIFEST, required=True),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=option_help("Validate only; do not download.")),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help=_INCLUDE_SCHEDULES_HELP,
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        help=_INDEPENDENT_HELP,
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
    manifest: str = manifest_opt(help=_PACK_MANIFEST, required=True),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=option_help("Validate only; do not deploy.")),
    remap: list[str] | None = remap_opt(
        help=GUID_REMAP_HELP + " Overrides pack/entry remap path refs for this run."
    ),
    publish: bool = typer.Option(
        False,
        "--publish",
        "-p",
        help=option_help("After dataflow create/update, run Apply Changes."),
    ),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help=_INCLUDE_SCHEDULES_HELP,
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        help=_INDEPENDENT_HELP,
    ),
) -> None:
    """Deploy all items in a multi-kind pack (ordered by kind)."""
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
    manifest: str = manifest_opt(help=_PACK_MANIFEST, required=True),
    dry_run: bool = dry_run_opt(help=option_help("Validate only; do not compare.")),
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help=_INCLUDE_SCHEDULES_HELP,
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        help=_INDEPENDENT_HELP,
    ),
) -> None:
    """Compare all items in a multi-kind pack (ordered by kind)."""
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
    manifest: str = manifest_opt(help=_PACK_MANIFEST, required=True),
    silent: bool = silent_opt(),
    dry_run: bool = dry_run_opt(help=option_help("Validate only; do not delete.")),
) -> None:
    """Delete all items in a multi-kind pack (reverse kind order)."""
    from fabric_tools.pack_run import run_pack_command

    run_pack_command(
        CommandMode.DELETE,
        manifest=manifest,
        silent=silent,
        dry_run=dry_run,
    )
