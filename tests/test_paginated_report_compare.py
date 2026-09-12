"""Tests for paginated-report compare."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fabric_tools.paginated_report.compare import compare_paginated_report
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.powerbi_client import PowerBiApiError

WS = "11111111-1111-1111-1111-111111111111"
REPORT = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

SAMPLE_RDL = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/'
    b'2016/01/reportdefinition">\n'
    b"  <Width>6.5in</Width>\n"
    b"</Report>\n"
)
OTHER_RDL = SAMPLE_RDL.replace(b"6.5in", b"8.5in")


class FakePowerBiClient:
    def __init__(self, rdls: dict[str, bytes], names: dict[str, str]) -> None:
        self.rdls = rdls
        self.names = names

    def get_group(self, group_id: str) -> dict[str, Any]:
        return {"id": group_id, "name": "Dev"}

    def get_report(self, group_id: str, report_id: str) -> dict[str, Any]:
        del group_id
        if report_id not in self.rdls:
            raise PowerBiApiError("missing", status_code=404)
        return {
            "id": report_id,
            "name": self.names[report_id],
            "reportType": "PaginatedReport",
        }

    def export_report_definition(self, group_id: str, report_id: str) -> bytes:
        del group_id
        if report_id not in self.rdls:
            raise PowerBiApiError("missing", status_code=404)
        return self.rdls[report_id]


def test_compare_identical_normalizing_newlines(tmp_path: Path) -> None:
    path = tmp_path / "Sales.rdl"
    path.write_bytes(SAMPLE_RDL.replace(b"\n", b"\r\n"))
    client = FakePowerBiClient({REPORT: SAMPLE_RDL}, {REPORT: "Sales"})
    item = WorkItem(Target(WS, REPORT), path)
    result = compare_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.identical
    assert result.diff_text == ""


def test_compare_reports_diff(tmp_path: Path) -> None:
    path = tmp_path / "Sales.rdl"
    path.write_bytes(OTHER_RDL)
    client = FakePowerBiClient({REPORT: SAMPLE_RDL}, {REPORT: "Sales"})
    item = WorkItem(Target(WS, REPORT), path)
    result = compare_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert "6.5in" in result.diff_text
    assert "8.5in" in result.diff_text


def test_compare_origin_to_target() -> None:
    client = FakePowerBiClient(
        {ORIGIN: SAMPLE_RDL, REPORT: OTHER_RDL},
        {ORIGIN: "A", REPORT: "B"},
    )
    item = WorkItem(Target(WS, REPORT), None, origin=Target(WS, ORIGIN))
    result = compare_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert "6.5in" in result.diff_text or "8.5in" in result.diff_text
