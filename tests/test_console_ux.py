"""Tests for Windows console double-click detection helpers."""

from __future__ import annotations

import sys

import pytest

from fabric_tools import console_ux


def test_owns_console_alone_false_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console_ux.sys, "platform", "linux")
    assert console_ux.owns_console_alone() is False


def test_owns_console_alone_true_when_parent_explorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console_ux.sys, "platform", "win32")
    monkeypatch.setattr(console_ux, "_parent_image_name", lambda: "explorer.exe")
    monkeypatch.setattr(console_ux, "_console_process_names", lambda: [])
    assert console_ux.owns_console_alone() is True


def test_owns_console_alone_false_when_shell_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console_ux.sys, "platform", "win32")
    monkeypatch.setattr(console_ux, "_parent_image_name", lambda: "powershell.exe")
    monkeypatch.setattr(
        console_ux,
        "_console_process_names",
        lambda: ["powershell.exe", "fabric-tools.exe"],
    )
    assert console_ux.owns_console_alone() is False


def test_owns_console_alone_true_with_terminal_host_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(console_ux.sys, "platform", "win32")
    monkeypatch.setattr(console_ux, "_parent_image_name", lambda: "windowsterminal.exe")
    monkeypatch.setattr(
        console_ux,
        "_console_process_names",
        lambda: ["openconsole.exe", "fabric-tools.exe"],
    )
    monkeypatch.setattr(
        console_ux, "_process_image_name", lambda _pid: "fabric-tools.exe"
    )
    assert console_ux.owns_console_alone() is True


def test_pause_uses_msvcrt_when_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(console_ux, "owns_console_alone", lambda: True)

    class FakeMsvcrt:
        @staticmethod
        def getch() -> bytes:
            calls.append("getch")
            return b"\r"

    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())
    console_ux.pause_if_double_clicked()
    assert calls == ["getch"]
