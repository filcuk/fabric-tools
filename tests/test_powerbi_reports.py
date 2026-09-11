"""Tests for semantic-model impact listing helpers on Power BI client."""

from __future__ import annotations

from typing import Any

from fabric_tools.powerbi_client import PowerBiClient


class _FakeHttp:
    def __init__(self, reports: list[dict[str, Any]]) -> None:
        self.reports = reports
        self.closed = False

    def get(self, url: str, headers: dict[str, str] | None = None) -> Any:
        del headers
        assert url.endswith("/reports")

        class _Resp:
            status_code = 200
            content = b"{}"
            text = "{}"

            def json(self) -> dict[str, Any]:
                return {"value": reports}

        reports = self.reports
        return _Resp()

    def close(self) -> None:
        self.closed = True


def test_reports_bound_to_dataset_filters() -> None:
    http = _FakeHttp(
        [
            {"id": "r1", "name": "A", "datasetId": "ds1"},
            {"id": "r2", "name": "B", "datasetId": "ds2"},
            {"id": "r3", "name": "C", "datasetId": "ds1"},
        ]
    )
    client = PowerBiClient(get_token=lambda: "tok", client=http)  # type: ignore[arg-type]
    bound = client.reports_bound_to_dataset("ws", "ds1")
    assert [r["id"] for r in bound] == ["r1", "r3"]
