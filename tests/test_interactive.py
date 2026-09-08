"""Tests for interactive wizard prompt assembly."""

from __future__ import annotations

from typing import Any

import pytest
import typer

from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.interactive import run_interactive_wizard
from fabric_tools.parsing import CommandMode


def test_interactive_dispatches_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = iter(
        [
            "notebook",
            "compare",
            "./a.ipynb",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    def fake_prompt(text: str, default: Any = None) -> str:
        return next(prompts)

    def fake_confirm(text: str, default: bool = False) -> bool:
        lowered = text.lower()
        if "ignore" in lowered or "proceed" in lowered:
            return True
        return False

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("typer.prompt", fake_prompt)
    monkeypatch.setattr("typer.confirm", fake_confirm)
    monkeypatch.setattr(
        "fabric_tools.interactive.run_notebook_command",
        fake_run,
        raising=False,
    )
    # Wizard imports run_notebook_command from cli inside the function.
    monkeypatch.setattr("fabric_tools.cli.run_notebook_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.COMPARE
    assert captured["kwargs"]["file_values"] == ["./a.ipynb"]
    assert captured["kwargs"]["ignore_outputs"] is True


def test_interactive_abort_on_proceed(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = iter(
        [
            "notebook",
            "download",
            "./a.ipynb",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )

    monkeypatch.setattr("typer.prompt", lambda *a, **k: next(prompts))
    monkeypatch.setattr(
        "typer.confirm",
        lambda text, default=False: False,
    )

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == EXIT_USER
