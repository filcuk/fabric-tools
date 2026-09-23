"""CLI wiring for run / refresh commands."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from fabric_tools.cli import app
from fabric_tools.sync.kinds.item_jobs import (
    DATAFLOW_REFRESH,
    NOTEBOOK_RUN,
    PIPELINE_RUN,
    SEMANTIC_MODEL_REFRESH,
)

WS = "11111111-1111-1111-1111-111111111111"
ITEM = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

COMMANDS = [
    ("notebook", "run", "fabric_tools.cli.commands.notebook.run_notebook_run_command"),
    ("pipeline", "run", "fabric_tools.cli.commands.pipeline.run_pipeline_run_command"),
    (
        "dataflow",
        "refresh",
        "fabric_tools.cli.commands.dataflow.run_dataflow_refresh_command",
    ),
    (
        "semantic-model",
        "refresh",
        "fabric_tools.cli.commands.semantic_model.run_semantic_model_refresh_command",
    ),
]


@pytest.mark.parametrize(("group", "verb", "_runner"), COMMANDS)
def test_group_help_lists_job_command(group: str, verb: str, _runner: str) -> None:
    result = CliRunner().invoke(app, [group, "--help"])

    assert result.exit_code == 0
    assert verb in result.stdout


@pytest.mark.parametrize(("group", "verb", "_runner"), COMMANDS)
def test_job_command_help_lists_flags(group: str, verb: str, _runner: str) -> None:
    result = CliRunner().invoke(app, [group, verb, "--help"])

    assert result.exit_code == 0
    for flag in ("--no-wait", "-w", "--target", "--manifest", "--filter", "--dry-run"):
        assert flag in result.stdout
    assert "--origin" not in result.stdout


@pytest.mark.parametrize(("group", "verb", "runner"), COMMANDS)
def test_job_command_passes_options_to_runner(
    monkeypatch: pytest.MonkeyPatch, group: str, verb: str, runner: str
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runner, lambda **kwargs: calls.append(kwargs))

    result = CliRunner().invoke(
        app,
        [group, verb, "-t", f"{WS}:*", "-f", "sales", "-s", "-d", "-w"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "target_values": [f"{WS}:*"],
            "manifest": None,
            "name_filter": "sales",
            "silent": True,
            "dry_run": True,
            "no_wait": True,
        }
    ]


@pytest.mark.parametrize(("group", "verb", "runner"), COMMANDS)
def test_job_command_waits_by_default(
    monkeypatch: pytest.MonkeyPatch, group: str, verb: str, runner: str
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runner, lambda **kwargs: calls.append(kwargs))

    result = CliRunner().invoke(app, [group, verb, "-t", f"{WS}:{ITEM}"])

    assert result.exit_code == 0, result.output
    assert calls[0]["no_wait"] is False
    assert calls[0]["silent"] is False


def test_job_specs_use_expected_job_types() -> None:
    assert (NOTEBOOK_RUN.backend, NOTEBOOK_RUN.job_type) == ("fabric", "RunNotebook")
    assert (PIPELINE_RUN.backend, PIPELINE_RUN.job_type) == ("fabric", "Pipeline")
    assert PIPELINE_RUN.progress is not None
    assert (DATAFLOW_REFRESH.backend, DATAFLOW_REFRESH.job_type) == (
        "fabric",
        "Refresh",
    )
    assert DATAFLOW_REFRESH.execution_data == {"executeOption": "ApplyChangesIfNeeded"}
    assert SEMANTIC_MODEL_REFRESH.backend == "powerbi"
    assert NOTEBOOK_RUN.progress is None
    assert DATAFLOW_REFRESH.progress is None
