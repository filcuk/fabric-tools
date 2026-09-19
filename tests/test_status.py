"""Tests for activity status helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fabric_tools import status


def test_short_guid() -> None:
    assert status.short_guid("a1b2c3d4-e5f6-7890-abcd-ef1234567890") == "a1b2c3d4…"
    assert status.short_guid("abc") == "abc"
    assert status.short_guid("abcdefghij", length=4) == "abcd…"


def test_progress_message() -> None:
    assert (
        status.progress_message(1, 4, "report: comparing (a1b2c3d4…)…")
        == "1 of 4 · report: comparing (a1b2c3d4…)…"
    )


def test_status_detail() -> None:
    assert (
        status.status_detail(
            "notebook", "downloading", "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )
        == "notebook: downloading (a1b2c3d4…)…"
    )
    assert status.status_detail("report", "comparing", "Sales") == (
        "report: comparing (Sales)…"
    )
    assert status.status_detail("report", "creating") == "report: creating…"


def test_batch_progress_advance_and_skip(monkeypatch: object) -> None:
    messages: list[str] = []
    monkeypatch.setattr(status, "update", lambda msg: messages.append(msg))
    progress = status.BatchProgress(total=3)
    progress.advance("report: downloading (aaaaaaaa…)…")
    progress.skip_planned()
    progress.advance("report: downloading (bbbbbbbb…)…")
    assert progress.current == 2
    assert progress.total == 2
    assert messages == [
        "1 of 3 · report: downloading (aaaaaaaa…)…",
        "2 of 2 · report: downloading (bbbbbbbb…)…",
    ]


def test_update_outside_busy_is_noop() -> None:
    status.update("should not raise")


def test_busy_non_tty_prints_message() -> None:
    printed: list[str] = []

    console = MagicMock()
    console.is_terminal = False
    console.print = lambda msg, **_kwargs: printed.append(str(msg))

    with patch.object(status, "_console", console):
        with status.busy(status.status_detail("auth", "authenticating")):
            status.update(status.status_detail("notebook", "downloading"))
            status.update(status.status_detail("notebook", "downloading"))
            status.update("1 of 2 · report: comparing (a1b2c3d4…)…")

    assert printed == [
        "auth: authenticating…",
        "notebook: downloading…",
        "1 of 2 · report: comparing (a1b2c3d4…)…",
    ]


def test_busy_nested_restores_parent_message() -> None:
    updates: list[str] = []

    fake_status = MagicMock()
    fake_status.update = lambda msg: updates.append(str(msg))

    console = MagicMock()
    console.is_terminal = True
    console.status = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(return_value=fake_status),
            __exit__=MagicMock(return_value=False),
        )
    )

    with patch.object(status, "_console", console), status.busy("Outer..."):
        with status.busy("Inner..."):
            pass

    assert updates == ["Inner...", "Outer..."]


def test_clear_stops_active_status() -> None:
    fake_status = MagicMock()
    console = MagicMock()
    console.is_terminal = True
    console.status = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(return_value=fake_status),
            __exit__=MagicMock(return_value=False),
        )
    )

    with patch.object(status, "_console", console), status.busy("Working..."):
        status.clear()
        fake_status.stop.assert_called_once()

    # No active spinner: clear is a no-op.
    status.clear()


def test_print_error_panel_clears_busy_spinner() -> None:
    from fabric_tools.colours import print_error_panel

    with (
        patch("fabric_tools.status.clear") as clear_mock,
        patch("rich.console.Console"),
    ):
        print_error_panel("boom")
    clear_mock.assert_called_once_with()


def test_print_warn_panel_clears_busy_spinner() -> None:
    from fabric_tools.colours import print_warn_panel

    with (
        patch("fabric_tools.status.clear") as clear_mock,
        patch("rich.console.Console"),
    ):
        print_warn_panel("careful")
    clear_mock.assert_called_once_with()
