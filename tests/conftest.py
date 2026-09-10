"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from fabric_tools.update_check import (
    DISABLE_UPDATE_CHECK_ENV,
    reset_background_update_check,
)


@pytest.fixture(autouse=True)
def _disable_background_update_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep CLI tests offline and isolated from GitHub / day-cache state."""
    monkeypatch.setenv(DISABLE_UPDATE_CHECK_ENV, "1")
    reset_background_update_check()
    yield
    reset_background_update_check()
