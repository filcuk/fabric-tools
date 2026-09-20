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
    selects = iter(["notebook", "compare", "execute", "file"])
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
    assert captured["kwargs"]["on_success"] is not None


def test_interactive_dry_run_offers_manifest_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selects = iter(["notebook", "download", "dry_both"])
    texts = iter(
        [
            "./a.ipynb",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    confirms = iter([False, True])  # add another?, proceed?
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
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.cli.run_notebook_command", fake_run)

    with pytest.raises(typer.Exit):
        run_interactive_wizard()
    assert captured["kwargs"]["dry_run"] is True
    assert captured["kwargs"]["on_success"] is not None


def test_prompt_save_manifest_writes_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    from pathlib import Path

    from fabric_tools.interactive import prompt_save_manifest
    from fabric_tools.parsing import Target, WorkItem

    confirms = iter([True])
    texts = iter([str(tmp_path / "deploy")])

    monkeypatch.setattr(
        "questionary.confirm",
        lambda *a, **k: _Ask(next(confirms)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    items = [
        WorkItem(
            Target(
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ),
            tmp_path / "a.ipynb",
        )
    ]
    prompt_save_manifest(items, display_names=["A"])
    written = tmp_path / "deploy.ftdep"
    assert written.is_file()
    assert "notebook" in written.read_text(encoding="utf-8")


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


def test_interactive_notebook_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    selects = iter(["notebook", "delete", "execute"])
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    confirms = iter([False, True, True])  # add another?, silent?, proceed?
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
    assert captured["mode"] is CommandMode.DELETE
    assert captured["kwargs"]["on_success"] is None


def test_interactive_dataflow_gen1_download(monkeypatch: pytest.MonkeyPatch) -> None:
    selects = iter(["dataflow-gen1", "download", "execute"])
    texts = iter(
        [
            "./model.json",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    confirms = iter([False, True, True])  # add another?, silent?, proceed?
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

    monkeypatch.setattr("fabric_tools.cli.run_dataflow_gen1_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DOWNLOAD
    assert captured["kwargs"]["file_values"] == ["./model.json"]
    assert captured["kwargs"]["on_success"] is not None
