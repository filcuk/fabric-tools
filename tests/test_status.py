"""Tests for activity status helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fabric_tools import status


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
        == "notebook: downloading (a1b2c3d)…"
    )


def test_status_detail_appends_progress_detail() -> None:
    assert (
        status.status_detail("pipeline", "running", "Sales", detail="3/12 Copy1")
        == "pipeline: running (Sales) · 3/12 Copy1…"
    )
    assert (
        status.status_detail("pipeline", "running", detail="3/12 Copy1")
        == "pipeline: running · 3/12 Copy1…"
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


def test_batch_progress_plan_extra(monkeypatch: object) -> None:
    messages: list[str] = []
    monkeypatch.setattr(status, "update", lambda msg: messages.append(msg))
    progress = status.BatchProgress(total=1)
    progress.plan_extra(1)
    progress.advance("report: downloading (Sales)…")
    progress.advance("semantic-model: downloading (Sales)…")
    assert progress.current == 2
    assert progress.total == 2
    assert messages == [
        "1 of 2 · report: downloading (Sales)…",
        "2 of 2 · semantic-model: downloading (Sales)…",
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
    class FakeHandle:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def update(self, message: str) -> None:
            self.messages.append(message)

        def stop(self) -> None:
            return None

    outer = FakeHandle()
    token = status._active.set(outer)
    msg_token = status._message.set("Outer...")
    try:
        with status.busy("Inner..."):
            pass
    finally:
        status._message.reset(msg_token)
        status._active.reset(token)

    assert outer.messages == ["Inner...", "Outer..."]


def test_set_percent_suffixes_message_without_changing_it() -> None:
    handle = MagicMock()
    token = status._active.set(handle)
    msg_token = status._message.set("notebook: downloading (Sales)…")
    try:
        status.set_percent(42)
        handle.update.assert_called_with("notebook: downloading (Sales)… 42%")
        assert status.current_message() == "notebook: downloading (Sales)…"
        status.set_percent(None)
        handle.update.assert_called_with("notebook: downloading (Sales)…")
    finally:
        status._message.reset(msg_token)
        status._active.reset(token)


def test_set_percent_outside_busy_is_noop() -> None:
    status.set_percent(50)


def test_set_aside_under_busy_handle() -> None:
    asides: list[object] = []

    class FakeHandle:
        def __init__(self) -> None:
            self.aside = None

        def update(self, message: str) -> None:
            del message

        def set_aside(self, renderable: object) -> None:
            self.aside = renderable
            asides.append(renderable)

        def stop(self) -> None:
            return None

    handle = FakeHandle()
    token = status._active.set(handle)  # type: ignore[arg-type]
    try:
        status.set_aside("note")
        assert handle.aside == "note"
        status.warn_aside("careful")
        assert handle.aside is not None
        assert status.current_aside() is handle.aside
        status.clear_aside()
        assert handle.aside is None
    finally:
        status._active.reset(token)

    assert asides[0] == "note"
    assert asides[-1] is None


def test_warn_aside_accepts_rich_text() -> None:
    from rich.text import Text

    asides: list[object] = []

    class FakeHandle:
        aside = None

        def set_aside(self, renderable: object) -> None:
            self.aside = renderable
            asides.append(renderable)

    handle = FakeHandle()
    token = status._active.set(handle)  # type: ignore[arg-type]
    try:
        body = Text("Use ")
        body.append("--independent", style="magenta")
        status.warn_aside(body)
        assert handle.aside is not None
    finally:
        status._active.reset(token)

    assert asides


def test_set_aside_outside_busy_prints() -> None:
    printed: list[object] = []
    console = MagicMock()
    console.is_terminal = True
    console.print = lambda msg, **_kwargs: printed.append(msg)

    with patch.object(status, "_console", console):
        status.set_aside("alone")
        status.clear_aside()  # no-op outside busy
    assert printed == ["alone"]


def test_clear_stops_active_status() -> None:
    handle = MagicMock()
    token = status._active.set(handle)
    try:
        status.clear()
        handle.stop.assert_called_once()
    finally:
        status._active.reset(token)

    # No active spinner: clear is a no-op.
    status.clear()


def test_busy_handle_stop_skips_console_line() -> None:
    """Regression: Rich Live.stop() calls console.line(); we must not."""
    console = MagicMock()
    console.is_terminal = True
    console.clear_live = MagicMock()
    console.pop_render_hook = MagicMock()
    console.show_cursor = MagicMock()
    console.control = MagicMock()
    console.line = MagicMock()

    live = MagicMock()
    live._lock = __import__("threading").RLock()
    live._started = True
    live.console = console
    live.auto_refresh = False
    live._refresh_thread = None
    live.transient = True
    live._alt_screen = False
    live._live_render = MagicMock()
    live._live_render.position_cursor.return_value = ""
    live._live_render.restore_cursor.return_value = ""
    live._disable_redirect_io = MagicMock()

    handle = status._BusyHandle(live=live, spinner=MagicMock())
    handle.stop()

    console.line.assert_not_called()
    console.show_cursor.assert_called_with(True)
    live._disable_redirect_io.assert_called_once()
    live._live_render.position_cursor.assert_called_once()
    live._live_render.restore_cursor.assert_not_called()


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


def test_print_info_panel_clears_busy_spinner() -> None:
    from fabric_tools.colours import print_info_panel

    with (
        patch("fabric_tools.status.clear") as clear_mock,
        patch("rich.console.Console"),
    ):
        print_info_panel("tip")
    clear_mock.assert_called_once_with()


def test_print_success_panel_clears_busy_spinner() -> None:
    from fabric_tools.colours import print_success_panel

    with (
        patch("fabric_tools.status.clear") as clear_mock,
        patch("rich.console.Console"),
    ):
        print_success_panel("done")
    clear_mock.assert_called_once_with()


def test_run_spinner_swatch_zero_waits_prints_steps() -> None:
    printed: list[str] = []
    console = MagicMock()
    console.is_terminal = False
    console.print = lambda msg, **_kwargs: printed.append(str(msg))

    with patch.object(status, "_console", console):
        status.run_spinner_swatch(step_seconds=(0.0, 0.0, 0.0), percent_interval=0.0)

    assert printed == [
        "1 of 3 · debug: connecting (Example)…",
        "2 of 3 · debug: loading (Example)…",
        "3 of 3 · debug: deploying (Example)…",
    ]


def test_run_spinner_swatch_ticks_percent(monkeypatch: object) -> None:
    from contextlib import contextmanager

    percents: list[int | None] = []
    sleeps: list[float] = []

    @contextmanager
    def _busy(_message: str):
        yield

    monkeypatch.setattr(status, "busy", _busy)
    monkeypatch.setattr(status, "update", lambda _msg: None)
    monkeypatch.setattr(status, "set_percent", lambda p: percents.append(p))
    monkeypatch.setattr(status, "sleep", lambda s: sleeps.append(s))

    status.run_spinner_swatch()

    assert percents == list(range(0, 101))
    assert sleeps[:2] == [1.0, 2.0]
    assert sleeps[2:] == [0.05] * 100
