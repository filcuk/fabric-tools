"""Confirm helpers print display names with short GUIDs."""

from __future__ import annotations

from typing import Any

import pytest

from fabric_tools import confirm
from fabric_tools.client import FabricApiError
from fabric_tools.display import GUID_LENGTH_ENV
from fabric_tools.parsing import Target

WS = "11111111-2222-3333-4444-555555555555"
ITEM = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER = "ffffffff-0000-1111-2222-333333333333"


@pytest.fixture(autouse=True)
def _default_guid_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GUID_LENGTH_ENV, raising=False)


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        if self.fail:
            raise FabricApiError("nope")
        return {"displayName": "Dev"}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        if self.fail:
            raise FabricApiError("nope")
        return {"displayName": "Sales", "type": "Notebook"}


def test_resolve_workspace_name_short_guid() -> None:
    assert confirm.resolve_workspace_name(FakeClient(), WS) == "Dev (1111111)"  # type: ignore[arg-type]


def test_resolve_item_name_short_guid() -> None:
    label = confirm.resolve_item_name(FakeClient(), Target(WS, ITEM))  # type: ignore[arg-type]
    assert label == "Sales (aaaaaaa, type=Notebook)"


def test_resolve_names_unavailable_short_guid() -> None:
    client = FakeClient(fail=True)
    assert confirm.resolve_workspace_name(client, WS).startswith(  # type: ignore[arg-type]
        "1111111 (unavailable:"
    )
    assert confirm.resolve_item_name(client, Target(WS, ITEM)).startswith(  # type: ignore[arg-type]
        "aaaaaaa (unavailable:"
    )


def test_resolve_names_full_guid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GUID_LENGTH_ENV, "full")
    assert confirm.resolve_workspace_name(FakeClient(), WS) == f"Dev ({WS})"  # type: ignore[arg-type]


def test_bound_report_lines_short_and_exclude(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePbi:
        def __enter__(self) -> FakePbi:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def ensure_authenticated(self) -> None:
            return None

        def reports_bound_to_dataset(
            self, workspace_id: str, dataset_id: str
        ) -> list[dict[str, Any]]:
            return [
                {"id": ITEM, "name": "Self"},
                {"id": OTHER, "name": "Other"},
            ]

    monkeypatch.setattr("fabric_tools.powerbi_client.PowerBiClient", FakePbi)
    lines, err = confirm._bound_report_lines(WS, "model", exclude_id=ITEM)
    assert err is None
    assert lines == ['report "Other" (fffffff)']
