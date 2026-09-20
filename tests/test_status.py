"""Tests for activity status helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fabric_tools import status


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
            status.update("Waiting for Fabric operation...")

    assert printed == [
        "Authenticating...",
        "Downloading notebook...",
        "Waiting for Fabric operation...",
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
