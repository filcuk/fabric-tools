"""Tests for report download/deploy/delete ops with a fake Fabric client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.definition_parts import PAYLOAD_TYPE
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.report.ops import (
    delete_report,
    deploy_report,
    download_report,
    run_deploy_batch,
    run_download_batch,
)
from fabric_tools.status import short_guid

WS = "11111111-1111-1111-1111-111111111111"
REPORT = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED_REPORT = "99999999-9999-9999-9999-999999999999"
CREATED_MODEL = "88888888-8888-8888-8888-888888888888"
MODEL = "77777777-7777-7777-7777-777777777777"


def _part(path: str, raw: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(raw).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _pbir_conn(model_id: str = MODEL) -> bytes:
    return json.dumps(
        {
            "version": "4.0",
            "datasetReference": {
                "byConnection": {"connectionString": f"semanticmodelid={model_id}"}
            },
        }
    ).encode("utf-8")


def _pbir_path(relative: str = "../Sales.SemanticModel") -> bytes:
    return json.dumps(
        {
            "version": "4.0",
            "datasetReference": {"byPath": {"path": relative}},
        }
    ).encode("utf-8")


def _report_definition(*, body: str = '{"version": "1.0"}\n') -> dict[str, Any]:
    return {
        "format": "PBIR",
        "parts": [
            _part("definition.pbir", _pbir_conn()),
            _part("definition/report.json", body.encode("utf-8")),
        ],
    }


def _sm_definition() -> dict[str, Any]:
    return {
        "format": "TMDL",
        "parts": [
            _part("definition.pbism", json.dumps({"version": "5.0"}).encode("utf-8")),
            _part("definition/model.tmdl", b"model Sales\n"),
        ],
    }


def _write_report_folder(
    folder: Path,
    *,
    pbir: bytes | None = None,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "definition.pbir").write_bytes(pbir or _pbir_conn())
    (folder / "definition").mkdir(parents=True, exist_ok=True)
    (folder / "definition" / "report.json").write_text(
        '{"version": "1.0"}\n', encoding="utf-8"
    )
    return folder


def _write_model_folder(folder: Path) -> Path:
    (folder / "definition").mkdir(parents=True)
    (folder / "definition.pbism").write_text(
        json.dumps({"version": "5.0"}), encoding="utf-8"
    )
    (folder / "definition" / "model.tmdl").write_text("model Sales\n", encoding="utf-8")
    return folder


class FakeClient:
    def __init__(
        self,
        *,
        definitions_by_item: dict[str, dict[str, Any]] | None = None,
        sm_definitions: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.definitions_by_item = definitions_by_item or {
            REPORT: _report_definition(),
            ORIGIN: _report_definition(body='{"origin": true}\n'),
        }
        self.sm_definitions = sm_definitions or {MODEL: _sm_definition()}
        self.created_type: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        del wait
        self.calls.append((method, path, params, json))
        if method == "POST" and "/reports/" in path and path.endswith("/getDefinition"):
            item_id = path.split("/")[-2]
            return {"definition": self.definitions_by_item[item_id]}
        if (
            method == "POST"
            and "/semanticModels/" in path
            and path.endswith("/getDefinition")
        ):
            item_id = path.split("/")[-2]
            return {"definition": self.sm_definitions[item_id]}
        if method == "POST" and path.endswith("/items"):
            item_type = json.get("type")
            self.created_type = item_type
            if item_type == "SemanticModel":
                return {
                    "id": CREATED_MODEL,
                    "type": "SemanticModel",
                    "displayName": json["displayName"],
                }
            return {
                "id": CREATED_REPORT,
                "type": "Report",
                "displayName": json["displayName"],
            }
        if method == "POST" and path.endswith("/updateDefinition"):
            return None
        if method == "DELETE":
            return None
        raise FabricApiError(f"unexpected {method} {path}")

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        del workspace_id
        return {"id": item_id, "displayName": "FromOrigin", "type": "Report"}


class FakePowerBi:
    def __init__(self, *, dataset_id: str | None = MODEL) -> None:
        self.dataset_id = dataset_id
        self.exports: list[str] = []
        self.imports: list[dict[str, Any]] = []

    def ensure_authenticated(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_report(self, group_id: str, report_id: str) -> dict[str, Any]:
        del group_id
        return {"id": report_id, "datasetId": self.dataset_id, "name": "Sales"}

    def export_report(
        self, group_id: str, report_id: str, *, download_type: str
    ) -> bytes:
        del group_id, report_id
        self.exports.append(download_type)
        if download_type == "IncludeModel":
            from fabric_tools.powerbi_client import PowerBiApiError

            raise PowerBiApiError("thin report", status_code=400)
        return b"PBIX-LIVE"

    def import_pbix(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.imports.append({"args": args, "kwargs": kwargs})
        return {
            "id": "import-1",
            "importState": "Succeeded",
            "reports": [{"id": CREATED_REPORT}],
            "datasets": [{"id": CREATED_MODEL}],
        }


def test_download_report_independent(tmp_path: Path) -> None:
    dest = tmp_path / "Sales.Report"
    client = FakeClient()
    result = download_report(
        client,
        WorkItem(Target(WS, REPORT), dest),  # type: ignore[arg-type]
        independent=True,
        powerbi_client=FakePowerBi(),
    )
    assert result.ok
    assert (dest / "definition" / "report.json").is_file()
    assert result.semantic_model_id is None


def test_download_report_joined(tmp_path: Path) -> None:
    dest = tmp_path / "Sales.Report"
    client = FakeClient()
    result = download_report(
        client,
        WorkItem(Target(WS, REPORT), dest),  # type: ignore[arg-type]
        independent=False,
        powerbi_client=FakePowerBi(),
    )
    assert result.ok
    assert (dest / "definition" / "report.json").is_file()
    assert (tmp_path / "Sales.SemanticModel" / "definition" / "model.tmdl").is_file()
    assert result.semantic_model_id == MODEL


def test_deploy_create_report_only(tmp_path: Path) -> None:
    folder = _write_report_folder(tmp_path / "Sales.Report")
    client = FakeClient()
    result = deploy_report(
        client,
        WorkItem(Target(WS, None), folder),  # type: ignore[arg-type]
        display_name="Sales",
        independent=True,
    )
    assert result.ok
    assert result.item_id == CREATED_REPORT
    assert any(c[0] == "POST" and c[1].endswith("/items") for c in client.calls)


def test_deploy_joined_create(tmp_path: Path) -> None:
    model = _write_model_folder(tmp_path / "Sales.SemanticModel")
    report = _write_report_folder(
        tmp_path / "Sales.Report",
        pbir=_pbir_path("../Sales.SemanticModel"),
    )
    del model
    client = FakeClient()
    result = deploy_report(
        client,
        WorkItem(Target(WS, None), report),  # type: ignore[arg-type]
        display_name="Sales",
    )
    assert result.ok
    assert result.item_id == CREATED_REPORT
    assert result.semantic_model_id == CREATED_MODEL
    create_types = [
        c[3].get("type")
        for c in client.calls
        if c[0] == "POST" and c[1].endswith("/items") and isinstance(c[3], dict)
    ]
    assert create_types == ["SemanticModel", "Report"]
    # Report definition should be rewritten to byConnection.
    report_payload = next(
        c[3]
        for c in client.calls
        if c[0] == "POST"
        and c[1].endswith("/items")
        and isinstance(c[3], dict)
        and c[3].get("type") == "Report"
    )
    parts = report_payload["definition"]["parts"]
    pbir_part = next(p for p in parts if p["path"] == "definition.pbir")
    pbir = json.loads(base64.b64decode(pbir_part["payload"]))
    assert "byConnection" in pbir["datasetReference"]
    assert CREATED_MODEL in pbir["datasetReference"]["byConnection"]["connectionString"]


def test_deploy_independent_with_packable_model_errors(tmp_path: Path) -> None:
    _write_model_folder(tmp_path / "Sales.SemanticModel")
    report = _write_report_folder(
        tmp_path / "Sales.Report",
        pbir=_pbir_path("../Sales.SemanticModel"),
    )
    result = deploy_report(
        FakeClient(),
        WorkItem(Target(WS, None), report),  # type: ignore[arg-type]
        independent=True,
    )
    assert not result.ok
    assert "independent" in result.message


def test_deploy_pbix_independent_errors(tmp_path: Path) -> None:
    pbix = tmp_path / "Sales.pbix"
    pbix.write_bytes(b"pbix")
    result = deploy_report(
        FakeClient(),
        WorkItem(Target(WS, None), pbix),  # type: ignore[arg-type]
        independent=True,
        powerbi_client=FakePowerBi(),
    )
    assert not result.ok
    assert ".pbix" in result.message


def test_deploy_pbix_create(tmp_path: Path) -> None:
    pbix = tmp_path / "Sales.pbix"
    pbix.write_bytes(b"pbix-bytes")
    pbi = FakePowerBi()
    result = deploy_report(
        FakeClient(),
        WorkItem(Target(WS, None), pbix),  # type: ignore[arg-type]
        display_name="Sales",
        powerbi_client=pbi,
    )
    assert result.ok
    assert result.item_id == CREATED_REPORT
    assert result.semantic_model_id == CREATED_MODEL
    assert pbi.imports


def test_download_pbix_falls_back_to_live_connect(tmp_path: Path) -> None:
    dest = tmp_path / "Sales.pbix"
    pbi = FakePowerBi()
    result = download_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), dest),  # type: ignore[arg-type]
        independent=False,
        powerbi_client=pbi,
    )
    assert result.ok
    assert dest.read_bytes() == b"PBIX-LIVE"
    assert pbi.exports == ["IncludeModel", "LiveConnect"]
    assert "thin/live-connect" in result.message


def test_delete_report(tmp_path: Path) -> None:
    del tmp_path
    client = FakeClient()
    result = delete_report(client, WorkItem(Target(WS, REPORT), None))  # type: ignore[arg-type]
    assert result.ok
    assert any(c[0] == "DELETE" and "/reports/" in c[1] for c in client.calls)


def test_run_download_batch_status_joined(tmp_path: Path, monkeypatch: Any) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: messages.append(msg),
    )
    dest_a = tmp_path / "A.Report"
    dest_b = tmp_path / "B.Report"
    report_b = "33333333-3333-3333-3333-333333333333"
    model_b = "88888888-8888-8888-8888-888888888888"
    client = FakeClient(
        definitions_by_item={
            REPORT: _report_definition(),
            report_b: {
                "format": "PBIR",
                "parts": [
                    _part("definition.pbir", _pbir_conn(model_b)),
                    _part("definition/report.json", b'{"version": "1.0"}\n'),
                ],
            },
        },
        sm_definitions={MODEL: _sm_definition(), model_b: _sm_definition()},
    )
    run_download_batch(
        client,
        [
            WorkItem(Target(WS, REPORT), dest_a),  # type: ignore[arg-type]
            WorkItem(Target(WS, report_b), dest_b),  # type: ignore[arg-type]
        ],
        powerbi_client=FakePowerBi(),
    )
    assert messages == [
        f"1 of 4 · Downloading report ({short_guid(REPORT)})…",
        f"2 of 4 · Downloading semantic model ({short_guid(MODEL)})…",
        f"3 of 4 · Downloading report ({short_guid(report_b)})…",
        f"4 of 4 · Downloading semantic model ({short_guid(model_b)})…",
    ]


def test_run_download_batch_status_independent(
    tmp_path: Path, monkeypatch: Any
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: messages.append(msg),
    )
    run_download_batch(
        FakeClient(),
        [WorkItem(Target(WS, REPORT), tmp_path / "Sales.Report")],  # type: ignore[arg-type]
        independent=True,
    )
    assert messages == [f"1 of 1 · Downloading report ({short_guid(REPORT)})…"]


def test_run_deploy_batch_status_joined_create(
    tmp_path: Path, monkeypatch: Any
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: messages.append(msg),
    )
    _write_model_folder(tmp_path / "Sales.SemanticModel")
    report = _write_report_folder(
        tmp_path / "Sales.Report",
        pbir=_pbir_path("../Sales.SemanticModel"),
    )
    run_deploy_batch(
        FakeClient(),
        [WorkItem(Target(WS, None), report)],  # type: ignore[arg-type]
        display_names=["Sales"],
    )
    assert messages == [
        "1 of 2 · Creating semantic model…",
        "2 of 2 · Creating report…",
    ]


def test_run_deploy_batch_status_joined_overwrite(
    tmp_path: Path, monkeypatch: Any
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: messages.append(msg),
    )
    _write_model_folder(tmp_path / "Sales.SemanticModel")
    report = _write_report_folder(
        tmp_path / "Sales.Report",
        pbir=_pbir_path("../Sales.SemanticModel"),
    )
    run_deploy_batch(
        FakeClient(),
        [WorkItem(Target(WS, REPORT), report)],  # type: ignore[arg-type]
        semantic_model_ids=[MODEL],
    )
    assert messages == [
        f"1 of 2 · Deploying semantic model ({short_guid(MODEL)})…",
        f"2 of 2 · Deploying report ({short_guid(REPORT)})…",
    ]
