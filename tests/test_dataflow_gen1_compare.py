"""Tests for Dataflow Gen1 compare."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fabric_tools.dataflow_gen1.compare import compare_dataflow
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.powerbi_client import PowerBiApiError

WS = "11111111-1111-1111-1111-111111111111"
DF = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class FakePowerBiClient:
    def __init__(self, models: dict[str, dict[str, Any]]) -> None:
        self.models = models

    def get_group(self, group_id: str) -> dict[str, Any]:
        return {"id": group_id, "name": "Dev"}

    def get_dataflow(self, group_id: str, dataflow_id: str) -> dict[str, Any]:
        model = self.models.get(dataflow_id)
        if model is None:
            raise PowerBiApiError("missing", status_code=404)
        return {"objectId": dataflow_id, "name": model["name"]}

    def get_dataflow_definition(
        self, group_id: str, dataflow_id: str
    ) -> dict[str, Any]:
        if dataflow_id not in self.models:
            raise PowerBiApiError("missing", status_code=404)
        return json.loads(json.dumps(self.models[dataflow_id]))


def test_compare_identical_ignoring_partitions(tmp_path: Path) -> None:
    remote = {
        "name": "Sales",
        "entities": [{"name": "Q1", "partitions": [{"name": "p"}]}],
    }
    local = {"name": "Sales", "entities": [{"name": "Q1"}]}
    path = tmp_path / "model.json"
    path.write_text(json.dumps(local), encoding="utf-8")
    client = FakePowerBiClient({DF: remote})
    item = WorkItem(Target(WS, DF), path)
    result = compare_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.identical
    assert result.diff_text == ""


def test_compare_reports_diff(tmp_path: Path) -> None:
    remote = {"name": "Sales", "entities": [{"name": "Q1"}]}
    local = {"name": "Sales", "entities": [{"name": "Q2"}]}
    path = tmp_path / "model.json"
    path.write_text(json.dumps(local), encoding="utf-8")
    client = FakePowerBiClient({DF: remote})
    item = WorkItem(Target(WS, DF), path)
    result = compare_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert "Q1" in result.diff_text
    assert "Q2" in result.diff_text


def test_compare_origin_to_target() -> None:
    client = FakePowerBiClient(
        {
            ORIGIN: {"name": "A", "entities": [{"name": "Q1"}]},
            DF: {"name": "B", "entities": [{"name": "Q1"}]},
        }
    )
    item = WorkItem(Target(WS, DF), None, origin=Target(WS, ORIGIN))
    result = compare_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert '"name": "A"' in result.diff_text or '"name": "B"' in result.diff_text
