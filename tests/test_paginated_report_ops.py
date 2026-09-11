"""Tests for paginated-report download/create/overwrite/delete ops."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fabric_tools.paginated_report.ops import (
    delete_paginated_report,
    deploy_paginated_report,
    download_paginated_report,
)
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.powerbi_client import PowerBiApiError

WS = "11111111-1111-1111-1111-111111111111"
REPORT = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED = "99999999-9999-9999-9999-999999999999"

SAMPLE_RDL = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/'
    b'2016/01/reportdefinition">\n'
    b"  <Width>6.5in</Width>\n"
    b"</Report>\n"
)
OTHER_RDL = SAMPLE_RDL.replace(b"6.5in", b"8.5in")


class FakePowerBiClient:
    def __init__(
        self,
        *,
        reports: dict[str, dict[str, Any]] | None = None,
        rdls: dict[str, bytes] | None = None,
        import_reports: list[dict[str, Any]] | None = None,
        listed: list[dict[str, Any]] | None = None,
    ) -> None:
        self.reports = reports or {
            REPORT: {
                "id": REPORT,
                "name": "Sales",
                "reportType": "PaginatedReport",
            },
            ORIGIN: {
                "id": ORIGIN,
                "name": "OriginRdl",
                "reportType": "PaginatedReport",
            },
        }
        self.rdls = rdls or {
            REPORT: SAMPLE_RDL,
            ORIGIN: OTHER_RDL,
        }
        self.import_reports = (
            import_reports
            if import_reports is not None
            else [{"id": CREATED, "name": "Sales"}]
        )
        self.listed = listed if listed is not None else []
        self.deleted: list[tuple[str, str]] = []
        self.last_import_bytes: bytes | None = None
        self.last_name_conflict: str | None = None
        self.last_display_name: str | None = None

    def get_report(self, group_id: str, report_id: str) -> dict[str, Any]:
        del group_id
        if report_id not in self.reports:
            raise PowerBiApiError("missing", status_code=404)
        return dict(self.reports[report_id])

    def export_report_definition(self, group_id: str, report_id: str) -> bytes:
        del group_id
        if report_id not in self.rdls:
            raise PowerBiApiError("missing", status_code=404)
        return self.rdls[report_id]

    def import_paginated_report(
        self,
        group_id: str,
        rdl_bytes: bytes,
        *,
        display_name: str,
        name_conflict: str = "Abort",
        wait: bool = True,
    ) -> dict[str, Any]:
        del group_id, wait
        self.last_import_bytes = rdl_bytes
        self.last_name_conflict = name_conflict
        self.last_display_name = display_name
        return {
            "id": "imp-1",
            "importState": "Succeeded",
            "reports": list(self.import_reports),
        }

    def list_reports(self, group_id: str) -> list[dict[str, Any]]:
        del group_id
        return list(self.listed)

    def delete_report(self, group_id: str, report_id: str) -> None:
        self.deleted.append((group_id, report_id))


def test_download_writes_rdl(tmp_path: Path) -> None:
    client = FakePowerBiClient()
    dest = tmp_path / "out.rdl"
    item = WorkItem(Target(WS, REPORT), dest)
    result = download_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert dest.read_bytes() == SAMPLE_RDL


def test_download_rejects_power_bi_report(tmp_path: Path) -> None:
    client = FakePowerBiClient(
        reports={
            REPORT: {
                "id": REPORT,
                "name": "Sales",
                "reportType": "PowerBIReport",
            }
        }
    )
    dest = tmp_path / "out.rdl"
    result = download_paginated_report(
        client,
        WorkItem(Target(WS, REPORT), dest),  # type: ignore[arg-type]
    )
    assert not result.ok
    assert "PaginatedReport" in result.message


def test_deploy_create_from_file(tmp_path: Path) -> None:
    client = FakePowerBiClient()
    src = tmp_path / "Sales.rdl"
    src.write_bytes(SAMPLE_RDL)
    item = WorkItem(Target(WS), src)
    result = deploy_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_name_conflict == "Abort"
    assert client.last_display_name == "Sales"
    assert client.last_import_bytes == SAMPLE_RDL


def test_deploy_create_with_explicit_name(tmp_path: Path) -> None:
    client = FakePowerBiClient()
    src = tmp_path / "Sales.rdl"
    src.write_bytes(SAMPLE_RDL)
    item = WorkItem(Target(WS), src)
    result = deploy_paginated_report(
        client,
        item,
        display_name="Renamed",  # type: ignore[arg-type]
    )
    assert result.ok
    assert client.last_display_name == "Renamed"


def test_deploy_create_from_origin() -> None:
    client = FakePowerBiClient()
    item = WorkItem(Target(WS), None, origin=Target(WS, ORIGIN))
    result = deploy_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_import_bytes == OTHER_RDL
    assert client.last_display_name == "OriginRdl"


def test_deploy_overwrite_uses_remote_name(tmp_path: Path) -> None:
    client = FakePowerBiClient()
    src = tmp_path / "local.rdl"
    src.write_bytes(OTHER_RDL)
    item = WorkItem(Target(WS, REPORT), src)
    result = deploy_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_name_conflict == "Overwrite"
    assert client.last_display_name == "Sales"
    assert "overwrote" in result.message


def test_deploy_overwrite_rejects_name_flag(tmp_path: Path) -> None:
    client = FakePowerBiClient()
    src = tmp_path / "local.rdl"
    src.write_bytes(SAMPLE_RDL)
    item = WorkItem(Target(WS, REPORT), src)
    result = deploy_paginated_report(
        client,
        item,
        display_name="Nope",  # type: ignore[arg-type]
    )
    assert not result.ok
    assert "--name" in result.message


def test_deploy_resolves_id_via_list_when_import_omits_reports(
    tmp_path: Path,
) -> None:
    client = FakePowerBiClient(
        import_reports=[],
        listed=[
            {
                "id": CREATED,
                "name": "Sales",
                "reportType": "PaginatedReport",
            }
        ],
    )
    src = tmp_path / "Sales.rdl"
    src.write_bytes(SAMPLE_RDL)
    item = WorkItem(Target(WS), src)
    result = deploy_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED


def test_delete_paginated_report() -> None:
    client = FakePowerBiClient()
    item = WorkItem(Target(WS, REPORT), None)
    result = delete_paginated_report(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.deleted == [(WS, REPORT)]


def test_delete_requires_item_id() -> None:
    client = FakePowerBiClient()
    item = WorkItem(Target(WS), None)
    result = delete_paginated_report(client, item)  # type: ignore[arg-type]
    assert not result.ok
