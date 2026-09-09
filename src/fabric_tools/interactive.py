"""Guided interactive CLI wizard with keyboard selections."""

from __future__ import annotations

from typing import Sequence

import typer
import questionary
from questionary import Choice

from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.manifest import (
    ManifestError,
    item_id_overrides_from_results,
    manifest_from_work_items,
    save_manifest,
)
from fabric_tools.notebook.compare import CompareResult
from fabric_tools.notebook.ops import OpResult
from fabric_tools.parsing import CommandMode, WorkItem


def run_interactive_wizard() -> None:
    """Prompt for tool/activity/parameters, then dispatch to the notebook command runner."""
    from fabric_tools.cli import run_notebook_command

    typer.echo("fabric-tools interactive mode")
    typer.echo("Use arrow keys + Enter to select. Ctrl+C cancels.\n")

    tool = _select(
        "Select tool",
        choices=["notebook"],
        default="notebook",
    )
    if tool != "notebook":
        typer.secho(f"Unsupported tool: {tool}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER)

    activity = _select(
        "Select activity",
        choices=["download", "upload", "compare"],
        default="download",
    )
    mode = CommandMode(activity)

    run_mode = _select(
        "How should this run?",
        choices=[
            Choice("Execute (download/upload/compare)", value="execute"),
            Choice("Dry-run: validate targets and files", value="dry_both"),
            Choice("Dry-run: validate remote targets only", value="dry_targets"),
            Choice("Dry-run: validate local files only", value="dry_files"),
        ],
        default="execute",
    )
    dry_run = run_mode != "execute"

    targets: list[str] = []
    files: list[str] = []
    names: list[str] = []

    if run_mode == "dry_targets":
        while True:
            target = _text(_target_prompt(mode), allow_empty=bool(targets))
            if not target:
                break
            targets.append(target)
            if not _confirm("Add another target?", default=False):
                break
    elif run_mode == "dry_files":
        while True:
            path = _text(
                "Enter file (.ipynb or *.Notebook folder)",
                allow_empty=bool(files),
            )
            if not path:
                break
            files.append(path)
            if not _confirm("Add another file?", default=False):
                break
    else:
        typer.echo("\nEnter file/target pairs.")
        while True:
            path = _text(
                "Enter file (.ipynb or *.Notebook folder)",
                allow_empty=bool(files and targets),
            )
            if not path:
                if files and targets:
                    break
                typer.echo("Enter at least one file/target pair.")
                continue

            target = _text(_target_prompt(mode), allow_empty=False)
            files.append(path)
            targets.append(target)

            if mode is CommandMode.UPLOAD and ":" not in target:
                name = _text(
                    "Display name for create (leave blank to derive from file)",
                    allow_empty=True,
                )
                names.append(name)

            if not _confirm("Add another file/target pair?", default=False):
                break

    silent = False
    ignore_outputs = False
    if not dry_run and mode is not CommandMode.COMPARE:
        silent = _confirm("Silent mode (skip confirmation prompts)?", default=False)
    if mode is CommandMode.COMPARE and not dry_run:
        ignore_outputs = _confirm(
            "Ignore notebook cell outputs in .ipynb diffs?",
            default=False,
        )

    resolved_names: list[str | None] | None = None
    if names:
        resolved_names = [n or None for n in names]

    typer.echo("\nSummary:")
    typer.echo(f"  tool:     {tool}")
    typer.echo(f"  activity: {activity}")
    typer.echo(f"  dry-run:  {dry_run}")
    if mode is not CommandMode.COMPARE:
        typer.echo(f"  silent:   {silent}")
    if targets:
        typer.echo(f"  targets:  {', '.join(targets)}")
    if files:
        typer.echo(f"  files:    {', '.join(files)}")
    if resolved_names:
        typer.echo(
            f"  names:    {', '.join(n or '(from file)' for n in resolved_names)}"
        )

    if not _confirm("Proceed?", default=True):
        typer.secho("Aborted by user.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=EXIT_USER)

    offer_manifest = bool(targets) and bool(files)

    run_notebook_command(
        mode,
        target_values=targets or None,
        file_values=files or None,
        silent=silent,
        dry_run=dry_run,
        names=resolved_names,
        ignore_outputs=ignore_outputs,
        on_success=prompt_save_manifest if offer_manifest else None,
    )


def prompt_save_manifest(
    items: Sequence[WorkItem],
    *,
    display_names: list[str] | None = None,
    op_results: list[OpResult] | None = None,
    compare_results: list[CompareResult] | None = None,
) -> None:
    """Ask whether to write a ``.ftdep`` after a successful interactive run or dry-run."""
    if op_results is not None and not all(result.ok for result in op_results):
        return
    if compare_results is not None and not all(result.ok for result in compare_results):
        return
    if not items:
        return
    if not _confirm("Save deployment manifest?", default=False):
        return

    stem = _text(
        "Manifest name or path (e.g. test → test.ftdep)",
        allow_empty=False,
    )
    overrides = (
        item_id_overrides_from_results(op_results) if op_results is not None else None
    )
    try:
        built = manifest_from_work_items(
            items,
            display_names=display_names,
            item_id_overrides=overrides,
        )
        path = save_manifest(stem, built)
    except ManifestError as exc:
        typer.secho(f"manifest not written: {exc}", fg=typer.colors.YELLOW, err=True)
        return
    typer.secho(f"Wrote manifest: {path}", fg=typer.colors.GREEN)


def _target_prompt(mode: CommandMode) -> str:
    if mode is CommandMode.UPLOAD:
        return "Enter target workspace GUID (create) or workspace:artifact (overwrite)"
    return "Enter target workspace:artifact"


def _select(
    message: str,
    *,
    choices: list[str] | list[Choice],
    default: str | None = None,
) -> str:
    result = questionary.select(
        message,
        choices=choices,
        default=default,
        instruction="(use arrow keys)",
    ).ask()
    if result is None:
        raise typer.Exit(code=EXIT_USER)
    return str(result)


def _confirm(message: str, *, default: bool = False) -> bool:
    result = questionary.confirm(message, default=default).ask()
    if result is None:
        raise typer.Exit(code=EXIT_USER)
    return bool(result)


def _text(message: str, *, allow_empty: bool) -> str:
    while True:
        result = questionary.text(message).ask()
        if result is None:
            raise typer.Exit(code=EXIT_USER)
        value = result.strip()
        if value or allow_empty:
            return value
        typer.echo("A value is required.")
