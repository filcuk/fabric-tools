"""Guided interactive CLI wizard with keyboard selections."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NoReturn

import questionary
import typer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from questionary import Choice, Style

from fabric_tools.colours import FG_OK, echo_cli_hint, print_warn_panel
from fabric_tools.confirm import CONFIRM_ABORT_MESSAGE
from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.manifest import (
    KIND_DATAFLOW,
    KIND_DATAFLOW_GEN1,
    KIND_ENVIRONMENT,
    KIND_NOTEBOOK,
    KIND_ORG_APP,
    KIND_PAGINATED_REPORT,
    KIND_PIPELINE,
    KIND_REPORT,
    KIND_SEMANTIC_MODEL,
    KIND_UDF,
    KIND_VARIABLE_LIBRARY,
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
    "environment": KIND_ENVIRONMENT,
    "org-app": KIND_ORG_APP,
    "variable-library": KIND_VARIABLE_LIBRARY,
    "pipeline": KIND_PIPELINE,
    "udf": KIND_UDF,
    "semantic-model": KIND_SEMANTIC_MODEL,
    "report": KIND_REPORT,
    "paginated-report": KIND_PAGINATED_REPORT,
}

_BACK_VALUE = "__back__"
_RLS_LIST = "role_list"
_RLS_MEMBER_ADD = "role_member_add"
_RLS_MEMBER_REMOVE = "role_member_remove"
_RLS_ACTIVITIES = frozenset({_RLS_LIST, _RLS_MEMBER_ADD, _RLS_MEMBER_REMOVE})
_STEPS = ("tool", "activity", "run_mode", "source", "inputs", "options", "proceed")
_STEP_KEYS: dict[str, tuple[str, ...]] = {
    "tool": ("tool",),
    "activity": ("activity",),
    "run_mode": ("run_mode",),
    "source": ("source_kind",),
    "inputs": ("targets", "files", "origins", "names"),
    "options": (
        "silent",
        "ignore_outputs",
        "independent",
        "include_schedules",
        "publish",
        "remap_values",
        "role_name",
        "member_name",
    ),
    "proceed": (),
}


class _Back(Exception):
    """User asked to return to the previous major wizard step."""


def _abort_by_user() -> NoReturn:
    """Exit interactive with the shared Warning panel used elsewhere in the CLI."""
    print_warn_panel(CONFIRM_ABORT_MESSAGE)
    raise typer.Exit(code=EXIT_USER) from None


def _ask_question(question: questionary.Question) -> Any:
    """Ask without questionary's plain ``Cancelled by user`` KBI line."""
    try:
        return question.unsafe_ask()
    except KeyboardInterrupt:
        _abort_by_user()


def _is_rls_activity(activity: str) -> bool:
    return activity in _RLS_ACTIVITIES


def run_interactive_wizard() -> None:
    """Prompt for tool/activity/parameters, then dispatch to the matching runner."""
    from fabric_tools.sync import (
        run_dataflow_command,
        run_dataflow_gen1_command,
        run_environment_command,
        run_notebook_command,
        run_org_app_command,
        run_paginated_report_command,
        run_pipeline_command,
        run_report_command,
        run_semantic_model_command,
        run_semantic_model_role_command,
        run_udf_command,
        run_variable_library_command,
    )

    echo_cli_hint("fabric-tools interactive mode")
    typer.echo(
        "Use arrow keys or 1-9 + Enter to select. "
        "Esc or ← Back goes to the previous step. Ctrl+C cancels.\n"
    )

    answers: dict[str, Any] = {}
    idx = 0
    while idx < len(_STEPS):
        step = _STEPS[idx]
        if step == "source" and not _needs_source_step(answers):
            answers.pop("source_kind", None)
            idx += 1
            continue
        try:
            _run_step(step, answers)
        except _Back:
            if idx == 0:
                _abort_by_user()
            idx -= 1
            while True:
                _clear_from(answers, _STEPS[idx])
                if _STEPS[idx] == "source" and not _needs_source_step(answers):
                    if idx == 0:
                        _abort_by_user()
                    idx -= 1
                    continue
                break
            continue
        idx += 1

    tool = str(answers["tool"])
    activity = str(answers["activity"])
    run_mode = str(answers["run_mode"])
    dry_run = run_mode != "execute"
    targets: list[str] = list(answers.get("targets") or [])
    silent = bool(answers.get("silent", False))

    if tool == "semantic-model" and _is_rls_activity(activity):
        role_action = {
            _RLS_LIST: "list",
            _RLS_MEMBER_ADD: "member_add",
            _RLS_MEMBER_REMOVE: "member_remove",
        }[activity]
        run_semantic_model_role_command(
            role_action,
            target_values=targets or None,
            silent=silent,
            dry_run=dry_run,
            role_name=answers.get("role_name"),
            member_name=answers.get("member_name"),
        )
        return

    mode = CommandMode(activity)
    files: list[str] = list(answers.get("files") or [])
    origins: list[str] = list(answers.get("origins") or [])
    names: list[str] = list(answers.get("names") or [])
    ignore_outputs = bool(answers.get("ignore_outputs", False))
    independent = bool(answers.get("independent", False))
    include_schedules = bool(answers.get("include_schedules", False))
    publish = bool(answers.get("publish", False))
    remap_values: list[str] | None = answers.get("remap_values")
    if remap_values is not None and not remap_values:
        remap_values = None

    resolved_names: list[str | None] | None = None
    if names:
        resolved_names = [n or None for n in names]

    offer_manifest = (
        mode is not CommandMode.DELETE
        and bool(targets)
        and (
            bool(files)
            or bool(origins)
            # Download may omit --target path; filled from remote names before save.
            or (mode is CommandMode.DOWNLOAD and not dry_run)
        )
    )
    kind = _TOOL_KIND[tool]
    on_success = (
        (lambda *a, **k: prompt_save_manifest(*a, kind=kind, **k))
        if offer_manifest
        else None
    )

    # Polymorphic CLI: download uses --origin=remote and optional --target=path.
    # Deploy/compare accept the same layout (roles inferred) or --target=remote
    # with --origin=path|remote; remote-to-remote stays origin → target.
    if mode is CommandMode.DOWNLOAD:
        cli_targets = files or None
        cli_origins = targets or None
    else:
        cli_targets = targets or None
        cli_origins = files or origins or None

    if tool == "dataflow-gen1":
        run_dataflow_gen1_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "dataflow":
        run_dataflow_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            remap_values=remap_values,
            publish=publish,
            on_success=on_success,
        )
    elif tool == "org-app":
        run_org_app_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "variable-library":
        run_variable_library_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "environment":
        run_environment_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "pipeline":
        run_pipeline_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            include_schedules=include_schedules,
            remap_values=remap_values,
            on_success=on_success,
        )
    elif tool == "udf":
        run_udf_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            remap_values=remap_values,
            on_success=on_success,
        )
    elif tool == "semantic-model":
        run_semantic_model_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    elif tool == "report":
        run_report_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            independent=independent,
            on_success=on_success,
        )
    elif tool == "paginated-report":
        run_paginated_report_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            on_success=on_success,
        )
    else:
        run_notebook_command(
            mode,
            target_values=cli_targets,
            origin_values=cli_origins,
            silent=silent,
            dry_run=dry_run,
            names=resolved_names,
            ignore_outputs=ignore_outputs,
            remap_values=remap_values,
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
    if not _confirm("Save deployment manifest?", default=False, allow_back=False):
        return

    stem = _text(
        "Manifest name or path (e.g. test → test.ftdep)",
        allow_empty=False,
        allow_back=False,
    )
    pack_remap: str | None = None
    if kind in {"notebook", "dataflow", "pipeline", "udf"} and _confirm(
        "Store a pack-level GUID remap path in the manifest?",
        default=False,
        allow_back=False,
    ):
        pack_remap = _text(
            "GUID remap JSON path (stored relative to the .ftdep)",
            allow_empty=False,
            allow_back=False,
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
            remap=pack_remap,
        )
        path, written = save_manifest(stem, built)
    except ManifestError as exc:
        print_warn_panel(f"manifest not written: {exc}")
        return
    if written:
        typer.secho(f"Wrote manifest: {path}", fg=FG_OK)


def _needs_source_step(answers: dict[str, Any]) -> bool:
    activity = answers.get("activity")
    run_mode = answers.get("run_mode")
    if activity is None or run_mode is None:
        return False
    if _is_rls_activity(str(activity)):
        return False
    mode = CommandMode(str(activity))
    if mode is CommandMode.DELETE:
        return False
    return mode in {CommandMode.DEPLOY, CommandMode.COMPARE} and run_mode not in {
        "dry_files",
        "dry_targets",
    }


def _clear_from(answers: dict[str, Any], step: str) -> None:
    started = False
    for name in _STEPS:
        if name == step:
            started = True
        if not started:
            continue
        for key in _STEP_KEYS[name]:
            answers.pop(key, None)


def _run_step(step: str, answers: dict[str, Any]) -> None:
    if step == "tool":
        answers["tool"] = _select(
            "Select tool",
            choices=[
                "notebook",
                "dataflow",
                "dataflow-gen1",
                "environment",
                "org-app",
                "variable-library",
                "pipeline",
                "udf",
                "semantic-model",
                "report",
                "paginated-report",
            ],
            default=answers.get("tool") or "notebook",
        )
        return

    if step == "activity":
        tool = str(answers["tool"])
        activity_choices: list[str | Choice] = [
            "download",
            "deploy",
            "compare",
            "delete",
        ]
        if tool == "semantic-model":
            activity_choices.extend(
                [
                    Choice("RLS: list roles", value=_RLS_LIST),
                    Choice("RLS: add member", value=_RLS_MEMBER_ADD),
                    Choice("RLS: remove member", value=_RLS_MEMBER_REMOVE),
                ]
            )
        answers["activity"] = _select(
            "Select activity",
            choices=activity_choices,
            default=answers.get("activity") or "download",
        )
        return

    if step == "run_mode":
        activity = str(answers["activity"])
        if _is_rls_activity(activity):
            if activity == _RLS_LIST:
                execute_label = "Execute (list RLS roles)"
            elif activity == _RLS_MEMBER_ADD:
                execute_label = "Execute (add RLS member)"
            else:
                execute_label = "Execute (remove RLS member)"
            run_choices = [
                Choice(execute_label, value="execute"),
                Choice("Dry-run: validate remote targets only", value="dry_targets"),
            ]
        else:
            mode = CommandMode(activity)
            if mode is CommandMode.DELETE:
                run_choices = [
                    Choice("Execute (delete)", value="execute"),
                    Choice(
                        "Dry-run: validate remote targets only", value="dry_targets"
                    ),
                ]
            else:
                run_choices = [
                    Choice(f"Execute ({activity})", value="execute"),
                    Choice("Dry-run: validate targets and sources", value="dry_both"),
                    Choice(
                        "Dry-run: validate remote targets only", value="dry_targets"
                    ),
                    Choice("Dry-run: validate local files only", value="dry_files"),
                ]
        answers["run_mode"] = _select(
            "How should this run?",
            choices=run_choices,
            default=answers.get("run_mode") or "execute",
        )
        return

    if step == "source":
        tool = str(answers["tool"])
        origin_label = _origin_label(tool)
        answers["source_kind"] = _select(
            "Select source",
            choices=[
                Choice("Local file / folder", value="file"),
                Choice(origin_label, value="origin"),
            ],
            default=answers.get("source_kind") or "file",
        )
        return

    if step == "inputs":
        _collect_inputs(answers)
        return

    if step == "options":
        _collect_options(answers)
        return

    if step == "proceed":
        if not _confirm("Proceed?", default=True):
            _abort_by_user()
        return

    raise RuntimeError(f"unknown wizard step: {step}")


def _file_prompt(tool: str) -> str:
    if tool == "dataflow-gen1":
        return "Enter file (stem or model.json)"
    if tool == "paginated-report":
        return "Enter file (stem or .rdl)"
    if tool == "dataflow":
        return "Enter folder (stem or *.Dataflow)"
    if tool == "org-app":
        return "Enter folder (stem or *.OrgApp)"
    if tool == "variable-library":
        return "Enter folder (stem or *.VariableLibrary)"
    if tool == "environment":
        return "Enter folder (stem or *.Environment)"
    if tool == "pipeline":
        return "Enter folder (stem or *.DataPipeline)"
    if tool == "udf":
        return "Enter folder (stem or *.UserDataFunction)"
    if tool == "semantic-model":
        return "Enter folder (stem or *.SemanticModel)"
    if tool == "report":
        return "Enter folder (stem or *.Report) or .pbix path"
    return "Enter file (stem, .ipynb, or *.Notebook folder)"


def _origin_label(tool: str) -> str:
    if tool in {"dataflow-gen1", "paginated-report"}:
        return "Power BI origin (workspace:artifact)"
    return "Fabric origin (workspace:artifact)"


def _resolved_source_kind(answers: dict[str, Any]) -> str:
    if "source_kind" in answers:
        return str(answers["source_kind"])
    activity = str(answers["activity"])
    if _is_rls_activity(activity):
        return "none"
    mode = CommandMode(activity)
    run_mode = str(answers["run_mode"])
    if mode is CommandMode.DELETE or run_mode == "dry_targets":
        return "none"
    return "file"


def _collect_inputs(answers: dict[str, Any]) -> None:
    tool = str(answers["tool"])
    activity = str(answers["activity"])
    run_mode = str(answers["run_mode"])
    source_kind = _resolved_source_kind(answers)
    file_prompt = _file_prompt(tool)

    targets: list[str] = []
    files: list[str] = []
    origins: list[str] = []
    names: list[str] = []

    if _is_rls_activity(activity) or activity == "delete" or run_mode == "dry_targets":
        target_mode = (
            CommandMode.DELETE
            if _is_rls_activity(activity) or activity == "delete"
            else CommandMode(activity)
        )
        while True:
            target = _text(
                _target_prompt(target_mode, tool=tool),
                allow_empty=bool(targets),
            )
            if not target:
                break
            targets.append(target)
            if not _confirm("Add another target?", default=False):
                break
    elif activity == "download" and run_mode != "dry_files":
        mode = CommandMode.DOWNLOAD
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
        mode = CommandMode(activity)
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
        mode = CommandMode(activity)
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

    answers["targets"] = targets
    answers["files"] = files
    answers["origins"] = origins
    answers["names"] = names


def _collect_options(answers: dict[str, Any]) -> None:
    tool = str(answers["tool"])
    activity = str(answers["activity"])
    run_mode = str(answers["run_mode"])
    dry_run = run_mode != "execute"
    targets: list[str] = list(answers.get("targets") or [])
    files: list[str] = list(answers.get("files") or [])
    origins: list[str] = list(answers.get("origins") or [])
    names: list[str] = list(answers.get("names") or [])

    silent = False
    ignore_outputs = False
    role_name: str | None = None
    member_name: str | None = None

    if _is_rls_activity(activity):
        if activity in {_RLS_MEMBER_ADD, _RLS_MEMBER_REMOVE}:
            role_name = _text("RLS role name", allow_empty=False)
            member_name = _text(
                "Member UPN or Entra group display name",
                allow_empty=False,
            )
        if not dry_run:
            silent = _confirm(
                "Silent mode (skip confirmation prompts)?",
                default=False,
            )

        typer.echo("\nSummary:")
        typer.echo(f"  tool:     {tool}")
        typer.echo(f"  activity: {_rls_activity_label(activity)}")
        typer.echo(f"  dry-run:  {dry_run}")
        typer.echo(f"  silent:   {silent}")
        if targets:
            typer.echo(f"  targets:  {', '.join(targets)}")
        if role_name:
            typer.echo(f"  role:     {role_name}")
        if member_name:
            typer.echo(f"  member:   {member_name}")

        answers["silent"] = silent
        answers["ignore_outputs"] = False
        answers["independent"] = False
        answers["include_schedules"] = False
        answers["publish"] = False
        answers["remap_values"] = None
        answers["role_name"] = role_name
        answers["member_name"] = member_name
        return

    mode = CommandMode(activity)
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

    publish = False
    if tool == "dataflow" and mode is CommandMode.DEPLOY:
        publish = _confirm(
            "Publish after deploy (Fabric Apply Changes / prepare for refresh)?",
            default=False,
        )
        typer.echo(f"  publish: {publish}")

    remap_values: list[str] | None = None
    if (
        mode is CommandMode.DEPLOY
        and tool in {"notebook", "dataflow", "pipeline", "udf"}
        and _confirm("Apply GUID remap file(s)?", default=False)
    ):
        echo_cli_hint("  Same as --remap / -r on deploy.")
        paths: list[str] = []
        while True:
            path = _text(
                "GUID remap JSON path",
                allow_empty=False,
            )
            paths.append(path)
            if not _confirm("Add another remap file?", default=False):
                break
        remap_values = paths
        typer.echo(f"  remap: {', '.join(paths)}")

    answers["silent"] = silent
    answers["ignore_outputs"] = ignore_outputs
    answers["independent"] = independent
    answers["include_schedules"] = include_schedules
    answers["publish"] = publish
    answers["remap_values"] = remap_values
    answers["role_name"] = None
    answers["member_name"] = None


def _rls_activity_label(activity: str) -> str:
    return {
        _RLS_LIST: "RLS: list roles",
        _RLS_MEMBER_ADD: "RLS: add member",
        _RLS_MEMBER_REMOVE: "RLS: remove member",
    }.get(activity, activity)


def _target_prompt(mode: CommandMode, *, tool: str) -> str:
    if mode is CommandMode.DELETE:
        return "Enter target workspace:artifact"
    if mode is CommandMode.DEPLOY:
        if tool == "dataflow-gen1":
            return "Enter target workspace GUID (create only)"
        return "Enter target workspace GUID (create) or workspace:artifact (overwrite)"
    return "Enter target workspace:artifact"


# questionary 2.1.x permanently reverse-styles `default` as checkbox-"selected"
# while the pointer moves (tmbo/questionary#473). Disable until a release with #503.
_SELECT_STYLE = Style([("selected", "noreverse")])


def _bind_escape_to_back(question: questionary.Question) -> None:
    bindings = question.application.key_bindings
    if bindings is None:
        return

    @bindings.add(Keys.Escape, eager=True)
    def _on_escape(event: Any) -> None:
        event.app.exit(result=_BACK_VALUE)


def _escape_key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add(Keys.Escape, eager=True)
    def _on_escape(event: Any) -> None:
        event.app.exit(result=_BACK_VALUE)

    return bindings


def _select(
    message: str,
    *,
    choices: Sequence[str | Choice],
    default: str | None = None,
    instruction: str | None = None,
    allow_back: bool = True,
) -> str:
    if instruction is None:
        instruction = (
            "(use arrow keys or 1-9; Esc/b back)"
            if allow_back
            else "(use arrow keys or 1-9)"
        )
    select_choices: list[str | Choice] = list(choices)
    if allow_back:
        select_choices.append(
            Choice("← Back", value=_BACK_VALUE, shortcut_key="b"),
        )
    question = questionary.select(
        message,
        choices=select_choices,
        default=default,
        instruction=instruction,
        style=_SELECT_STYLE,
        use_shortcuts=True,
    )
    if getattr(question, "application", None) is not None:
        _bind_escape_to_back(question)
    result = _ask_question(question)
    if result is None:
        _abort_by_user()
    if result == _BACK_VALUE:
        raise _Back()
    return str(result)


def _confirm(
    message: str,
    *,
    default: bool = False,
    allow_back: bool = True,
) -> bool:
    # Same select UX as other prompts (arrows / shortcuts + Enter).
    instruction = (
        "(use arrow keys or y/n; Esc/b back)"
        if allow_back
        else "(use arrow keys or y/n)"
    )
    return (
        _select(
            message,
            choices=[
                Choice("Yes", value="Yes", shortcut_key="y"),
                Choice("No", value="No", shortcut_key="n"),
            ],
            default="Yes" if default else "No",
            instruction=instruction,
            allow_back=allow_back,
        )
        == "Yes"
    )


def _text(
    message: str,
    *,
    allow_empty: bool,
    allow_back: bool = True,
) -> str:
    while True:
        kwargs: dict[str, Any] = {}
        if allow_back:
            kwargs["key_bindings"] = _escape_key_bindings()
            kwargs["instruction"] = "(Esc back)"
        question = questionary.text(message, **kwargs)
        result = _ask_question(question)
        if result is None:
            _abort_by_user()
        if result == _BACK_VALUE:
            raise _Back()
        value = str(result).strip()
        if value or allow_empty:
            return value
        typer.echo("Value required.")
