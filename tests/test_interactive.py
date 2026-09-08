"""Tests for interactive wizard prompt assembly."""

from __future__ import annotations

from typing import Any

import pytest
import typer

from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.interactive import run_interactive_wizard
from fabric_tools.parsing import CommandMode


class _Ask:
    def __init__(self, value: Any) -> None:
        self._value = value

    def ask(self) -> Any:
        return self._value


def test_interactive_dispatches_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    selects = iter(["notebook", "compare", "execute"])
    texts = iter(
        [
            "./a.ipynb",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    confirms = iter([False, True, True])  # add another?, ignore outputs?, proceed?
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )
    monkeypatch.setattr(
        "questionary.confirm",
        lambda *a, **k: _Ask(next(confirms)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.cli.run_notebook_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.COMPARE
    assert captured["kwargs"]["file_values"] == ["./a.ipynb"]
    assert captured["kwargs"]["ignore_outputs"] is True


def test_interactive_abort_on_proceed(monkeypatch: pytest.MonkeyPatch) -> None:
    selects = iter(["notebook", "download", "execute"])
    texts = iter(
        [
            "./a.ipynb",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    confirms = iter([False, False, False])  # add another?, silent?, proceed?

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )
    monkeypatch.setattr(
        "questionary.confirm",
        lambda *a, **k: _Ask(next(confirms)),
    )

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == EXIT_USER
