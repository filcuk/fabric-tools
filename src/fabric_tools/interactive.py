"""Guided interactive CLI wizard with keyboard selections."""

from __future__ import annotations

from collections.abc import Sequence

import questionary
import typer
from questionary import Choice

from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.manifest import (
    KIND_DATAFLOW,
    KIND_DATAFLOW_GEN1,
    KIND_NOTEBOOK,
    KIND_PAGINATED_REPORT,
    KIND_PIPELINE,
    KIND_REPORT,
    KIND_SEMANTIC_MODEL,
    KIND_UDF,
    ManifestError,
    item_id_overrides_from_results,
    manifest_from_work_items,
    save_manifest,
    semantic_model_id_overrides_from_results,
)
from fabric_tools.notebook.compare import CompareResult
from fabric_tools.notebook.ops import OpResult
from fabric_tools.parsing import CommandMode, WorkItem

_TOOL_KIND = {
    "notebook": KIND_NOTEBOOK,
    "dataflow": KIND_DATAFLOW,
    "dataflow-gen1": KIND_DATAFLOW_GEN1,
    "pipeline": KIND_PIPELINE,
    "udf": KIND_UDF,
    "semantic-model": KIND_SEMANTIC_MODEL,
    "report": KIND_REPORT,
    "paginated-report": KIND_PAGINATED_REPORT,
}


def run_interactive_wizard() -> None:
    """Prompt for tool/activity/parameters, then dispatch to the matching runner."""
    from fabric_tools.cli import (
        run_dataflow_command,
        run_dataflow_gen1_command,
        run_notebook_command,
        run_paginated_report_command,
        run_pipeline_command,
        run_report_command,
        run_semantic_model_command,
        run_udf_command,
    )

    typer.echo("fabric-tools interactive mode")
    typer.echo("Use arrow keys + Enter to select. Ctrl+C cancels.\n")

    tool = _select(
        "Select tool",
        choices=[
            "notebook",
            "dataflow",
            "dataflow-gen1",
            "pipeline",
            "udf",
            "semantic-model",
            "report",
            "paginated-report",
        ],
        default="notebook",
    )

    activity = _select(
        "Select activity",
        choices=["download", "deploy", "compare", "delete"],
        default="download",
    )
    mode = CommandMode(activity)

    if mode is CommandMode.DELETE:
        run_choices = [
            Choice("Execute (delete)", value="execute"),
            Choice("Dry-run: validate remote targets only", value="dry_targets"),
        ]
    else:
        run_choices = [
            Choice(f"Execute ({activity})", value="execute"),
            Choice("Dry-run: validate targets and sources", value="dry_both"),
            Choice("Dry-run: validate remote targets only", value="dry_targets"),
            Choice("Dry-run: validate local files only", value="dry_files"),
        ]

    run_mode = _select(
        "How should this run?",
        choices=run_choices,
        default="execute",
    )
    dry_run = run_mode != "execute"

    targets: list[str] = []
    files: list[str] = []
    origins: list[str] = []
    names: list[str] = []

    if tool == "dataflow-gen1":
        file_prompt = "Enter file (model.json)"
        origin_label = "Power BI origin (workspace:artifact)"
    elif tool == "paginated-report":
        file_prompt = "Enter file (.rdl)"
        origin_label = "Power BI origin (workspace:artifact)"
    elif tool == "dataflow":
        file_prompt = "Enter folder (*.Dataflow)"
        origin_label = "Fabric origin (workspace:artifact)"
    elif tool == "pipeline":
        file_prompt = "Enter folder (*.DataPipeline)"
        origin_label = "Fabric origin (workspace:artifact)"
    elif tool == "udf":
        file_prompt = "Enter folder (*.UserDataFunction)"
        origin_label = "Fabric origin (workspace:artifact)"
    elif tool == "semantic-model":
        file_prompt = "Enter folder (*.SemanticModel)"
        origin_label = "Fabric origin (workspace:artifact)"
    elif tool == "report":
        file_prompt = "Enter folder (*.Report) or .pbix path"
        origin_label = "Fabric origin (workspace:artifact)"
    else:
        file_prompt = "Enter file (.ipynb or *.Notebook folder)"
        origin_label = "Fabric origin (workspace:artifact)"

    source_kind = "file"
    if mode is CommandMode.DELETE:
        source_kind = "none"
    elif mode in {CommandMode.DEPLOY, CommandMode.COMPARE} and run_mode != "dry_files":
        if run_mode == "dry_targets":
            source_kind = "none"
        else:
            source_kind = _select(
                "Select source",
                choices=[
                    Choice("Local file / folder", value="file"),
                    Choice(origin_label, value="origin"),
                ],
                default="file",
            )

    if mode is CommandMode.DELETE or run_mode == "dry_targets":
        while True:
            target = _text(_target_prompt(mode, tool=tool), allow_empty=bool(targets))
            if not target:
                break
            targets.append(target)
            if not _confirm("Add another target?", default=False):
                break
    elif mode is CommandMode.DOWNLOAD and run_mode != "dry_files":
        typer.echo("\nEnter target(s). Local path defaults to remote name + extension.")
        while True:
            target = _text(_target_prompt(mode, tool=tool), allow_empty=bool(targets))
            if not target:
                break
            targets.append(target)
            if not _confirm("Add another target?", default=False):
                break
        if _confirm("Specify local destination path(s)?", default=False):
            for target in targets:
                files.append(_text(f"{file_prompt} for {target}", allow_empty=False))
    elif run_mode == "dry_files":
        while True:
            path = _text(file_prompt, allow_empty=bool(files))
            if not path:
                break
            files.append(path)
            if not _confirm("Add another file?", default=False):
                break
    elif source_kind == "origin":
        typer.echo("\nEnter origin/target pairs.")
        while True:
            origin = _text(
                "Enter origin workspace:artifact",
                allow_empty=bool(origins and targets),
            )
            if not origin:
                if origins and targets:
                    break
                typer.echo("Enter at least one origin/target pair.")
                continue

            target = _text(_target_prompt(mode, tool=tool), allow_empty=False)
            origins.append(origin)
            targets.append(target)

            if mode is CommandMode.DEPLOY and ":" not in target:
                name = _text(
                    "Display name for create (leave blank to use origin name)",
                    allow_empty=True,
                )
                names.append(name)

            if not _confirm("Add another origin/target pair?", default=False):
                break
    else:
        typer.echo("\nEnter file/target pairs.")
        while True:
            path = _text(
                file_prompt,
                allow_empty=bool(files and targets),
            )
            if not path:
                if files and targets:
                    break
                typer.echo("Enter at least one file/target pair.")
                continue

            target = _text(_target_prompt(mode, tool=tool), allow_empty=False)
            files.append(path)
            targets.append(target)

            if mode is CommandMode.DEPLOY and ":" not in target:
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
    if tool == "notebook" and mode is CommandMode.COMPARE and not dry_run:
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
    if origins:
        typer.echo(f"  origins:  {', '.join(origins)}")
    if resolved_names:
        typer.echo(
            f"  names:    {', '.join(n or '(from source)' for n in resolved_names)}"
        )

    independent = False
    if tool == "report" and mode in {
        CommandMode.DOWNLOAD,
        CommandMode.DEPLOY,
        CommandMode.COMPARE,
    }:
        independent = _confirm(
            "Independent (report only — do not join semantic model)?",
            default=False,
        )
        typer.echo(f"  independent: {independent}")

    include_schedules = False
    if tool == "pipeline" and mode in {
        CommandMode.DOWNLOAD,
        CommandMode.DEPLOY,
        CommandMode.COMPARE,
    }:
        include_schedules = _confirm(
            "Include schedules (.schedules)? "
            "Default is pipeline-only (overwrite preserves remote schedules).",
            default=False,
        )
        typer.echo(f"  include-schedules: {include_schedules}")

    if not _confirm("Proceed?", default=True):
        typer.secho("Aborted by user.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=EXIT_USER)

    offer_manifest = (
        mode is not CommandMode.DELETE
        and bool(targets)
        and (
            bool(files)
            or bool(origins)
            # Download may omit --file; paths are filled from remote names before save.
            or (mode is CommandMode.DOWNLOAD and not dry_run)
        )
    )
    kind = _TOOL_KIND[tool]
    on_success = (
        (lambda *a, **k: prompt_save_manifest(*a, kind=kind, **k))
        if offer_manifest
        else None
    )

    if tool == "dataflow-gen1":
        run_dataflow_gen1_command(
            mode,
            target_values=targets or None,
            file_values=files or None,
            origin_values=origins or None,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "dataflow":
        run_dataflow_command(
            mode,
            target_values=targets or None,
            file_values=files or None,
            origin_values=origins or None,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "pipeline":
        run_pipeline_command(
            mode,
            target_values=targets or None,
            file_values=files or None,
            origin_values=origins or None,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            include_schedules=include_schedules,
            on_success=on_success,
        )
    elif tool == "udf":
        run_udf_command(
            mode,
            target_values=targets or None,
            file_values=files or None,
            origin_values=origins or None,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "semantic-model":
        run_semantic_model_command(
            mode,
            target_values=targets or None,
            file_values=files or None,
            origin_values=origins or None,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "report":
        run_report_command(
            mode,
            target_values=targets or None,
            file_values=files or None,
            origin_values=origins or None,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            independent=independent,
            on_success=on_success,
        )
    elif tool == "paginated-report":
        run_paginated_report_command(
            mode,
            target_values=targets or None,
            file_values=files or None,
            origin_values=origins or None,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    else:
        run_notebook_command(
            mode,
            target_values=targets or None,
            file_values=files or None,
            origin_values=origins or None,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            ignore_outputs=ignore_outputs,
            on_success=on_success,
        )


def prompt_save_manifest(
    items: Sequence[WorkItem],
    *,
    display_names: list[str] | None = None,
    op_results: list[OpResult] | None = None,
    compare_results: list[CompareResult] | None = None,
    kind: str = KIND_NOTEBOOK,
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
    sm_overrides = None
    if op_results is not None and kind == KIND_REPORT:
        from_results = semantic_model_id_overrides_from_results(op_results)
        if any(from_results):
            sm_overrides = from_results
    try:
        built = manifest_from_work_items(
            items,
            kind=kind,
            display_names=display_names,
            item_id_overrides=overrides,
            semantic_model_id_overrides=sm_overrides,
        )
        path = save_manifest(stem, built)
    except ManifestError as exc:
        typer.secho(f"manifest not written: {exc}", fg=typer.colors.YELLOW, err=True)
        return
    typer.secho(f"Wrote manifest: {path}", fg=typer.colors.GREEN)


def _target_prompt(mode: CommandMode, *, tool: str) -> str:
    if mode is CommandMode.DELETE:
        return "Enter target workspace:artifact"
    if mode is CommandMode.DEPLOY:
        if tool == "dataflow-gen1":
            return "Enter target workspace GUID (create only)"
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
        typer.echo("Value required.")
