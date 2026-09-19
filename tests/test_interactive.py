"""Tests for interactive wizard prompt assembly."""

from __future__ import annotations

from typing import Any

import pytest
import typer
from questionary import Choice

from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.interactive import run_interactive_wizard
from fabric_tools.parsing import CommandMode


class _Ask:
    def __init__(self, value: Any) -> None:
        self._value = value

    def ask(self) -> Any:
        return self._value


def _yn(value: bool) -> str:
    return "Yes" if value else "No"


def test_interactive_dispatches_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    # tool, activity, run_mode, source; then add another?, ignore outputs?, proceed?
    selects = iter(
        [
            "notebook",
            "compare",
            "execute",
            "file",
            _yn(False),
            _yn(True),
            _yn(True),
        ]
    )
    texts = iter(
        [
            "./a.ipynb",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_notebook_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.COMPARE
    assert captured["kwargs"]["origin_values"] == ["./a.ipynb"]
    assert captured["kwargs"].get("file_values") is None
    assert captured["kwargs"]["ignore_outputs"] is True
    assert captured["kwargs"]["on_success"] is not None


def test_interactive_dry_run_offers_manifest_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # tool, activity, run_mode; then add another?, specify paths?, proceed?
    selects = iter(
        ["notebook", "download", "dry_both", _yn(False), _yn(True), _yn(True)]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
            "./a.ipynb",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_notebook_command", fake_run)

    with pytest.raises(typer.Exit):
        run_interactive_wizard()
    assert captured["kwargs"]["dry_run"] is True
    assert captured["kwargs"]["on_success"] is not None
    assert captured["kwargs"]["origin_values"] == [
        "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222"
    ]
    assert captured["kwargs"]["target_values"] == ["./a.ipynb"]
    assert captured["kwargs"].get("file_values") is None


def test_prompt_save_manifest_writes_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:

    from fabric_tools.interactive import prompt_save_manifest
    from fabric_tools.parsing import Target, WorkItem

    selects = iter([_yn(True), _yn(False)])
    texts = iter([str(tmp_path / "deploy")])

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
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
    # tool, activity, run_mode; add another?, specify paths?, silent?, proceed?
    selects = iter(
        [
            "notebook",
            "download",
            "execute",
            _yn(False),
            _yn(False),
            _yn(False),
            _yn(False),
        ]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == EXIT_USER


def test_interactive_notebook_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    selects = iter(["notebook", "delete", "execute", _yn(False), _yn(True), _yn(True)])
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_notebook_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DELETE
    assert captured["kwargs"]["on_success"] is None


def test_interactive_dataflow_gen1_download(monkeypatch: pytest.MonkeyPatch) -> None:
    selects = iter(
        [
            "dataflow-gen1",
            "download",
            "execute",
            _yn(False),
            _yn(False),
            _yn(True),
            _yn(True),
        ]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_dataflow_gen1_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DOWNLOAD
    assert captured["kwargs"].get("file_values") is None
    assert captured["kwargs"]["on_success"] is not None


def test_interactive_paginated_report_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selects = iter(
        [
            "paginated-report",
            "download",
            "execute",
            _yn(False),
            _yn(False),
            _yn(True),
            _yn(True),
        ]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_paginated_report_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DOWNLOAD
    assert captured["kwargs"].get("file_values") is None
    assert captured["kwargs"]["on_success"] is not None


def test_interactive_dataflow_download(monkeypatch: pytest.MonkeyPatch) -> None:
    selects = iter(
        [
            "dataflow",
            "download",
            "execute",
            _yn(False),
            _yn(False),
            _yn(True),
            _yn(True),
        ]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_dataflow_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DOWNLOAD
    assert captured["kwargs"].get("file_values") is None
    assert captured["kwargs"]["on_success"] is not None


def test_interactive_variable_library_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selects = iter(
        [
            "variable-library",
            "download",
            "execute",
            _yn(False),
            _yn(False),
            _yn(True),
            _yn(True),
        ]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}
    monkeypatch.setattr("questionary.select", lambda *a, **k: _Ask(next(selects)))
    monkeypatch.setattr("questionary.text", lambda *a, **k: _Ask(next(texts)))

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_variable_library_command", fake_run)
    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DOWNLOAD
    assert captured["kwargs"].get("file_values") is None
    assert captured["kwargs"]["on_success"] is not None


def test_interactive_pipeline_download(monkeypatch: pytest.MonkeyPatch) -> None:
    # another target? destination paths? silent? include-schedules? proceed?
    selects = iter(
        [
            "pipeline",
            "download",
            "execute",
            _yn(False),
            _yn(False),
            _yn(True),
            _yn(False),
            _yn(True),
        ]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_pipeline_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DOWNLOAD
    assert captured["kwargs"].get("file_values") is None
    assert captured["kwargs"]["include_schedules"] is False
    assert captured["kwargs"]["on_success"] is not None


def test_interactive_pipeline_deploy_include_schedules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # another pair? silent? include-schedules? apply remap? proceed?
    selects = iter(
        [
            "pipeline",
            "deploy",
            "execute",
            "file",
            _yn(False),
            _yn(False),
            _yn(True),
            _yn(False),
            _yn(True),
        ]
    )
    texts = iter(
        [
            r".\ETL.DataPipeline",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_pipeline_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DEPLOY
    assert captured["kwargs"]["include_schedules"] is True
    assert captured["kwargs"]["remap_values"] is None
    assert captured["kwargs"]["origin_values"] == [r".\ETL.DataPipeline"]
    assert captured["kwargs"].get("file_values") is None
    assert captured["kwargs"]["target_values"] == [
        "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222"
    ]


def test_interactive_notebook_deploy_remap(monkeypatch: pytest.MonkeyPatch) -> None:
    # another pair? silent? apply remap? another remap? proceed?
    selects = iter(
        [
            "notebook",
            "deploy",
            "execute",
            "file",
            _yn(False),
            _yn(False),
            _yn(True),
            _yn(False),
            _yn(True),
        ]
    )
    texts = iter(
        [
            r".\etl.ipynb",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
            r".\prod.remap.json",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_notebook_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DEPLOY
    assert captured["kwargs"]["remap_values"] == [r".\prod.remap.json"]
    assert captured["kwargs"]["origin_values"] == [r".\etl.ipynb"]
    assert captured["kwargs"].get("file_values") is None


def test_interactive_dataflow_deploy_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    # another pair? silent? publish? apply remap? proceed?
    selects = iter(
        [
            "dataflow",
            "deploy",
            "execute",
            "file",
            _yn(False),
            _yn(False),
            _yn(True),
            _yn(False),
            _yn(True),
        ]
    )
    texts = iter(
        [
            r".\Sales.Dataflow",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_dataflow_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DEPLOY
    assert captured["kwargs"]["publish"] is True
    assert captured["kwargs"]["remap_values"] is None
    assert captured["kwargs"]["origin_values"] == [r".\Sales.Dataflow"]
    assert captured["kwargs"].get("file_values") is None


def test_interactive_udf_download(monkeypatch: pytest.MonkeyPatch) -> None:
    selects = iter(
        ["udf", "download", "execute", _yn(False), _yn(False), _yn(True), _yn(True)]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_udf_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DOWNLOAD
    assert captured["kwargs"].get("file_values") is None
    assert captured["kwargs"]["on_success"] is not None


def test_select_disables_stuck_default_highlight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_tools.interactive import _SELECT_STYLE, _select

    captured: dict[str, Any] = {}

    def fake_select(*_a: Any, **kwargs: Any) -> _Ask:
        captured.update(kwargs)
        return _Ask("b")

    monkeypatch.setattr("questionary.select", fake_select)

    assert _select("pick", choices=["a", "b"], default="a", allow_back=False) == "b"
    assert captured["style"] is _SELECT_STYLE
    assert ("selected", "noreverse") in captured["style"].style_rules
    assert captured["use_shortcuts"] is True
    assert captured["instruction"] == "(use arrow keys or 1-9)"


def test_confirm_uses_yes_no_select(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabric_tools.interactive import _BACK_VALUE, _SELECT_STYLE, _confirm

    captured: dict[str, Any] = {}

    def fake_select(*_a: Any, **kwargs: Any) -> _Ask:
        captured.update(kwargs)
        return _Ask("Yes")

    monkeypatch.setattr("questionary.select", fake_select)

    assert _confirm("ok?", default=False) is True
    assert captured["default"] == "No"
    assert captured["instruction"] == "(use arrow keys or y/n; Esc/b back)"
    assert captured["style"] is _SELECT_STYLE
    assert captured["use_shortcuts"] is True
    titles = [c.title if isinstance(c, Choice) else c for c in captured["choices"]]
    assert titles == ["Yes", "No", "← Back"]
    values = [c.value if isinstance(c, Choice) else c for c in captured["choices"]]
    assert values == ["Yes", "No", _BACK_VALUE]
    shortcuts = [c.shortcut_key for c in captured["choices"] if isinstance(c, Choice)]
    assert shortcuts == ["y", "n", "b"]


def test_select_back_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabric_tools.interactive import _BACK_VALUE, _Back, _select

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(_BACK_VALUE),
    )

    with pytest.raises(_Back):
        _select("pick", choices=["a", "b"])


def test_text_escape_raises_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from fabric_tools.interactive import _BACK_VALUE, _Back, _text

    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(_BACK_VALUE),
    )

    with pytest.raises(_Back):
        _text("path", allow_empty=False)


def test_interactive_back_on_first_step_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_tools.interactive import _BACK_VALUE

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(_BACK_VALUE),
    )

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == EXIT_USER


def test_interactive_back_reprompts_previous_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fabric_tools.interactive import _BACK_VALUE

    # tool; activity then Back; activity again; run_mode; add another?; silent?; proceed?
    selects = iter(
        [
            "notebook",
            "deploy",
            _BACK_VALUE,
            "download",
            "execute",
            _yn(False),
            _yn(False),
            _yn(False),
            _yn(True),
        ]
    )
    texts = iter(
        [
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ]
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "questionary.select",
        lambda *a, **k: _Ask(next(selects)),
    )
    monkeypatch.setattr(
        "questionary.text",
        lambda *a, **k: _Ask(next(texts)),
    )

    def fake_run(mode: CommandMode, **kwargs: Any) -> None:
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        raise typer.Exit(code=0)

    monkeypatch.setattr("fabric_tools.sync.run_notebook_command", fake_run)

    with pytest.raises(typer.Exit) as exc_info:
        run_interactive_wizard()
    assert exc_info.value.exit_code == 0
    assert captured["mode"] is CommandMode.DOWNLOAD
    assert captured["kwargs"]["dry_run"] is False
    assert captured["kwargs"].get("file_values") is None
