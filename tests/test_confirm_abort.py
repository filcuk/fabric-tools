"""Confirmation interrupt / decline → shared user-abort path."""

from __future__ import annotations

import io

import pytest
import typer

from fabric_tools.confirm import (
    CONFIRM_ABORT_MESSAGE,
    ConfirmationAborted,
    abort_interrupt_message,
    confirm_or_abort,
    finish_prompt_line,
    prompt_confirm,
)
from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.sync.common import _exit_user_abort


def test_finish_prompt_line_writes_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr("fabric_tools.confirm.sys.stdout", buf)
    finish_prompt_line()
    assert buf.getvalue() == "\n"


def test_finish_prompt_line_err_uses_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr("fabric_tools.confirm.sys.stderr", buf)
    finish_prompt_line(err=True)
    assert buf.getvalue() == "\n"


def test_prompt_confirm_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_tools.confirm.typer.confirm", lambda *_a, **_k: True)
    assert prompt_confirm("Go?") is True


def test_prompt_confirm_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_tools.confirm.typer.confirm", lambda *_a, **_k: False)
    assert prompt_confirm("Go?") is False


def test_prompt_confirm_abort_returns_false_and_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buf = io.StringIO()
    monkeypatch.setattr("fabric_tools.confirm.sys.stdout", buf)

    def boom(*_a: object, **_k: object) -> bool:
        raise typer.Abort()

    monkeypatch.setattr("fabric_tools.confirm.typer.confirm", boom)
    assert prompt_confirm("Go?") is False
    assert buf.getvalue() == "\n"


def test_confirm_or_abort_silent_skips_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> bool:
        raise AssertionError("must not prompt when silent")

    monkeypatch.setattr("fabric_tools.confirm.prompt_confirm", boom)
    confirm_or_abort("Sure?", silent=True)


def test_confirm_or_abort_decline_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_tools.confirm.prompt_confirm", lambda *_a, **_k: False)
    with pytest.raises(ConfirmationAborted, match=CONFIRM_ABORT_MESSAGE):
        confirm_or_abort("Sure?", silent=False)


def test_confirm_or_abort_interrupt_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl+C/EOF must become ConfirmationAborted, not empty typer.Abort."""
    buf = io.StringIO()
    monkeypatch.setattr("fabric_tools.confirm.sys.stdout", buf)

    def boom(*_a: object, **_k: object) -> bool:
        raise typer.Abort()

    monkeypatch.setattr("fabric_tools.confirm.typer.confirm", boom)
    with pytest.raises(ConfirmationAborted, match=CONFIRM_ABORT_MESSAGE):
        confirm_or_abort("Sure?", silent=False)
    assert buf.getvalue() == "\n"


def test_abort_interrupt_message(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr("fabric_tools.confirm.sys.stdout", buf)
    assert abort_interrupt_message() == CONFIRM_ABORT_MESSAGE
    assert buf.getvalue() == "\n"


def test_exit_user_abort_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    panels: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.sync.common.print_warn_panel",
        lambda msg: panels.append(msg),
    )
    with pytest.raises(typer.Exit) as exc_info:
        _exit_user_abort(ConfirmationAborted(CONFIRM_ABORT_MESSAGE))
    assert exc_info.value.exit_code == EXIT_USER
    assert panels == [CONFIRM_ABORT_MESSAGE]


def test_exit_user_abort_typer_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.StringIO()
    panels: list[str] = []
    monkeypatch.setattr("fabric_tools.confirm.sys.stdout", buf)
    monkeypatch.setattr(
        "fabric_tools.sync.common.print_warn_panel",
        lambda msg: panels.append(msg),
    )
    with pytest.raises(typer.Exit) as exc_info:
        _exit_user_abort(typer.Abort())
    assert exc_info.value.exit_code == EXIT_USER
    assert panels == [CONFIRM_ABORT_MESSAGE]
    assert buf.getvalue() == "\n"


def test_ensure_sqlserver_default_confirm_handles_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default confirm must use prompt_confirm so Abort is not a hard failure."""
    from fabric_tools.xmla_roles import (
        INSTALL_HINT,
        XmlaRolesError,
        ensure_sqlserver_module,
    )

    monkeypatch.setattr(
        "fabric_tools.xmla_roles.sqlserver_module_available", lambda **_k: False
    )
    monkeypatch.setattr("fabric_tools.status.clear", lambda: None)

    def boom(*_a: object, **_k: object) -> bool:
        raise typer.Abort()

    monkeypatch.setattr("fabric_tools.confirm.typer.confirm", boom)
    with pytest.raises(XmlaRolesError, match="Aborted by user") as exc_info:
        ensure_sqlserver_module()
    assert INSTALL_HINT in str(exc_info.value)
