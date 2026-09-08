"""Guided interactive CLI wizard."""

from __future__ import annotations

import typer

from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.parsing import CommandMode


def run_interactive_wizard() -> None:
    """Prompt for tool/activity/parameters, then dispatch to the notebook command runner."""
    # Import lazily to avoid circular imports with cli.
    from fabric_tools.cli import run_notebook_command

    typer.echo("fabric-tools interactive mode")
    typer.echo("Press Ctrl+C to cancel at any time.\n")

    tool = _prompt_choice(
        "Select tool",
        choices=["notebook"],
        default="notebook",
    )
    if tool != "notebook":
        typer.secho(f"Unsupported tool: {tool}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER)

    activity = _prompt_choice(
        "Select activity",
        choices=["download", "upload", "compare"],
        default="download",
    )
    mode = CommandMode(activity)

    dry_run = typer.confirm("Dry-run only (validate, no sync/compare)?", default=False)

    targets: list[str] = []
    files: list[str] = []
    names: list[str] = []

    if dry_run and typer.confirm(
        "Validate remote targets only (skip local files)?",
        default=False,
    ):
        while True:
            target = typer.prompt(_target_prompt(mode), default="").strip()
            if not target:
                if targets:
                    break
                typer.echo("Enter at least one target, or cancel with Ctrl+C.")
                continue
            targets.append(target)
            if not typer.confirm("Add another target?", default=False):
                break
    elif dry_run and typer.confirm(
        "Validate local files only (skip remote targets)?",
        default=False,
    ):
        while True:
            path = typer.prompt(
                "Enter file (.ipynb or *.Notebook folder)",
                default="",
            ).strip()
            if not path:
                if files:
                    break
                typer.echo("Enter at least one file, or cancel with Ctrl+C.")
                continue
            files.append(path)
            if not typer.confirm("Add another file?", default=False):
                break
    else:
        typer.echo("\nEnter file/target pairs. Leave file blank when finished (after at least one).")
        while True:
            path = typer.prompt(
                "Enter file (.ipynb or *.Notebook folder)",
                default="",
            ).strip()
            if not path:
                if files and targets:
                    break
                typer.echo("Enter at least one file/target pair, or cancel with Ctrl+C.")
                continue

            target = typer.prompt(_target_prompt(mode)).strip()
            while not target:
                typer.echo("Target is required for this pair.")
                target = typer.prompt(_target_prompt(mode)).strip()

            files.append(path)
            targets.append(target)

            if mode is CommandMode.UPLOAD and ":" not in target:
                name = typer.prompt(
                    "Display name for create (Enter = derive from file)",
                    default="",
                ).strip()
                names.append(name)

            if not typer.confirm("Add another file/target pair?", default=False):
                break

    silent = False
    ignore_outputs = True
    if not dry_run and mode is not CommandMode.COMPARE:
        silent = typer.confirm("Silent mode (skip confirmation prompts)?", default=False)
    if mode is CommandMode.COMPARE and not dry_run:
        ignore_outputs = typer.confirm(
            "Ignore notebook cell outputs in .ipynb diffs?",
            default=True,
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

    if not typer.confirm("\nProceed?", default=True):
        typer.secho("Aborted by user.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=EXIT_USER)

    run_notebook_command(
        mode,
        target_values=targets or None,
        file_values=files or None,
        silent=silent,
        dry_run=dry_run,
        names=resolved_names,
        ignore_outputs=ignore_outputs,
    )


def _target_prompt(mode: CommandMode) -> str:
    if mode is CommandMode.UPLOAD:
        return "Enter target workspace GUID (create) or workspace:artifact (overwrite)"
    return "Enter target workspace:artifact"


def _prompt_choice(label: str, *, choices: list[str], default: str) -> str:
    choices_text = "/".join(choices)
    while True:
        value = typer.prompt(f"{label} [{choices_text}]", default=default).strip().lower()
        if value in choices:
            return value
        typer.echo(f"Please choose one of: {choices_text}")
