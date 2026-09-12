"""Tests for Power BI report list / export / import helpers."""

from __future__ import annotations

from typing import Any

from fabric_tools.powerbi_client import (
    PowerBiClient,
    report_and_dataset_ids_from_import,
)


class _FakeHttp:
    def __init__(self, reports: list[dict[str, Any]]) -> None:
        self.reports = reports
        self.closed = False
        self.posts: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        del headers, params
        if "Export" in url:

            class _ExportResp:
                status_code = 200
                content = b"PBIXDATA"
                text = ""

                def json(self) -> dict[str, Any]:
                    return {}

            return _ExportResp()

        if "/reports/" in url and not url.rstrip("/").endswith("/reports"):

            class _ReportResp:
                status_code = 200
                content = b"{}"
                text = "{}"

                def json(self) -> dict[str, Any]:
                    return {"id": "r1", "datasetId": "ds1", "name": "Sales"}

            return _ReportResp()

        class _Resp:
            status_code = 200
            content = b"{}"
            text = "{}"

            def json(self) -> dict[str, Any]:
                return {"value": reports}

        reports = self.reports
        return _Resp()

    def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        files: Any = None,
    ) -> Any:
        self.posts.append({"url": url, "params": params, "files": files})
        del headers

        class _Resp:
            status_code = 202
            content = b'{"id":"imp1"}'
            text = '{"id":"imp1"}'

            def json(self) -> dict[str, Any]:
                return {"id": "imp1"}

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


def test_get_report_and_export() -> None:
    http = _FakeHttp([])
    client = PowerBiClient(get_token=lambda: "tok", client=http)  # type: ignore[arg-type]
    report = client.get_report("ws", "r1")
    assert report["datasetId"] == "ds1"
    payload = client.export_report("ws", "r1", download_type="LiveConnect")
    assert payload == b"PBIXDATA"


def test_import_pbix_skip_report_param() -> None:
    http = _FakeHttp([])
    client = PowerBiClient(
        get_token=lambda: "tok",
        client=http,  # type: ignore[arg-type]
        sleep=lambda _: None,
    )
    result = client.import_pbix(
        "ws",
        b"bytes",
        dataset_display_name="Sales.pbix",
        skip_report=True,
        wait=False,
    )
    assert result["id"] == "imp1"
    assert http.posts[0]["params"]["skipReport"] == "true"


def test_report_and_dataset_ids_from_import() -> None:
    report_id, dataset_id = report_and_dataset_ids_from_import(
        {
            "reports": [{"id": "r9"}],
            "datasets": [{"id": "d9"}],
        }
    )
    assert report_id == "r9"
    assert dataset_id == "d9"
