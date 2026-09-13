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
        status.progress_message(1, 4, "Comparing report (a1b2c3d4…)…")
        == "1 of 4 · Comparing report (a1b2c3d4…)…"
    )


def test_status_detail() -> None:
    assert (
        status.status_detail(
            "Downloading", "notebook", "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )
        == "Downloading notebook (a1b2c3d4…)…"
    )
    assert status.status_detail("Comparing", "report", "Sales") == (
        "Comparing report (Sales)…"
    )
    assert status.status_detail("Creating", "report") == "Creating report…"


def test_batch_progress_advance_and_skip(monkeypatch: object) -> None:
    messages: list[str] = []
    monkeypatch.setattr(status, "update", lambda msg: messages.append(msg))
    progress = status.BatchProgress(total=3)
    progress.advance("Downloading report (aaaaaaaa…)…")
    progress.skip_planned()
    progress.advance("Downloading report (bbbbbbbb…)…")
    assert progress.current == 2
    assert progress.total == 2
    assert messages == [
        "1 of 3 · Downloading report (aaaaaaaa…)…",
        "2 of 2 · Downloading report (bbbbbbbb…)…",
    ]


def test_update_outside_busy_is_noop() -> None:
    status.update("should not raise")


def test_busy_non_tty_prints_message() -> None:
    printed: list[str] = []

    console = MagicMock()
    console.is_terminal = False
    console.print = lambda msg, **_kwargs: printed.append(str(msg))

    with patch.object(status, "_console", console):
        with status.busy("Authenticating..."):
            status.update("Downloading notebook...")
            status.update("Downloading notebook...")  # duplicate ignored
            status.update("1 of 2 · Comparing report (a1b2c3d4…)…")

    assert printed == [
        "Authenticating...",
        "Downloading notebook...",
        "1 of 2 · Comparing report (a1b2c3d4…)…",
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
