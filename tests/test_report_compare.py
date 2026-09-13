"""Tests for report compare."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.definition_parts import PAYLOAD_TYPE
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.report.compare import compare_report, run_compare_batch

WS = "11111111-1111-1111-1111-111111111111"
REPORT = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MODEL = "77777777-7777-7777-7777-777777777777"
ORIGIN_MODEL = "66666666-6666-6666-6666-666666666666"


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


def _definition(
    body: str = '{"version": "1.0"}\n', *, model_id: str = MODEL
) -> dict[str, Any]:
    return {
        "format": "PBIR",
        "parts": [
            _part("definition.pbir", _pbir_conn(model_id)),
            _part("definition/report.json", body.encode("utf-8")),
        ],
    }


def _sm_definition(*, body: str = "model Sales\n") -> dict[str, Any]:
    return {
        "format": "TMDL",
        "parts": [
            _part("definition.pbism", json.dumps({"version": "5.0"}).encode("utf-8")),
            _part("definition/model.tmdl", body.encode("utf-8")),
        ],
    }


def _write_local(folder: Path, *, body: str = '{"version": "1.0"}\n') -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "definition.pbir").write_bytes(_pbir_conn())
    (folder / "definition").mkdir(parents=True, exist_ok=True)
    (folder / "definition" / "report.json").write_text(body, encoding="utf-8")
    return folder


def _write_model(folder: Path, *, body: str = "model Sales\n") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "definition").mkdir(parents=True, exist_ok=True)
    (folder / "definition.pbism").write_text(
        json.dumps({"version": "5.0"}), encoding="utf-8"
    )
    (folder / "definition" / "model.tmdl").write_text(body, encoding="utf-8")
    return folder


class FakeClient:
    def __init__(
        self,
        *,
        remote_body: str = '{"version": "1.0"}\n',
        sm_bodies: dict[str, str] | None = None,
        report_defs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.remote_body = remote_body
        self.sm_bodies = sm_bodies or {MODEL: "model Sales\n"}
        self.report_defs = report_defs

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        del params, json, wait
        if method == "POST" and "/reports/" in path and path.endswith("/getDefinition"):
            item_id = path.split("/")[-2]
            if self.report_defs is not None:
                return {"definition": self.report_defs[item_id]}
            body = self.remote_body
            if item_id == ORIGIN:
                body = '{"origin": true}\n'
            model_id = ORIGIN_MODEL if item_id == ORIGIN else MODEL
            return {"definition": _definition(body, model_id=model_id)}
        if (
            method == "POST"
            and "/semanticModels/" in path
            and path.endswith("/getDefinition")
        ):
            item_id = path.split("/")[-2]
            return {"definition": _sm_definition(body=self.sm_bodies[item_id])}
        raise FabricApiError(f"unexpected {method} {path}")

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        del workspace_id
        return {"id": item_id, "displayName": "Sales", "type": "Report"}

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "WS"}


class FakePowerBi:
    def __init__(self, *, dataset_id: str | None = None) -> None:
        self.dataset_id = dataset_id

    def ensure_authenticated(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_report(self, group_id: str, report_id: str) -> dict[str, Any]:
        del group_id
        return {"id": report_id, "datasetId": self.dataset_id, "name": "Sales"}


def test_compare_identical(tmp_path: Path) -> None:
    local = _write_local(tmp_path / "Sales.Report")
    results = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), local),  # type: ignore[arg-type]
    )
    assert len(results) == 1
    assert results[0].ok
    assert results[0].identical
    assert results[0].remote_name == "Sales"
    assert results[0].local_name == "Sales.Report"
    assert results[0].target_ref == f"{WS}:{REPORT}"
    assert str(tmp_path) not in results[0].local_name


def test_compare_diff(tmp_path: Path) -> None:
    local = _write_local(tmp_path / "Sales.Report", body='{"version": "2.0"}\n')
    results = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), local),  # type: ignore[arg-type]
    )
    assert len(results) == 1
    assert results[0].ok
    assert not results[0].identical
    assert results[0].diff_text


def test_compare_rejects_pbix(tmp_path: Path) -> None:
    pbix = tmp_path / "Sales.pbix"
    pbix.write_bytes(b"x")
    results = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), pbix),  # type: ignore[arg-type]
    )
    assert len(results) == 1
    assert not results[0].ok
    assert ".pbix" in (results[0].error or "")


def test_compare_origin(tmp_path: Path) -> None:
    del tmp_path
    results = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), None, origin=Target(WS, ORIGIN)),  # type: ignore[arg-type]
        independent=True,
    )
    assert len(results) == 1
    assert results[0].ok
    assert not results[0].identical


def test_compare_joined_file_identical(tmp_path: Path) -> None:
    report = _write_local(tmp_path / "Sales.Report")
    _write_model(tmp_path / "Sales.SemanticModel")
    results = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), report),  # type: ignore[arg-type]
    )
    assert len(results) == 2
    assert all(r.ok and r.identical for r in results)
    assert str(tmp_path / "Sales.SemanticModel") in results[1].header


def test_compare_joined_file_model_diff(tmp_path: Path) -> None:
    report = _write_local(tmp_path / "Sales.Report")
    _write_model(tmp_path / "Sales.SemanticModel", body="model Changed\n")
    results = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), report),  # type: ignore[arg-type]
    )
    assert len(results) == 2
    assert results[0].ok and results[0].identical
    assert results[1].ok and not results[1].identical
    assert results[1].diff_text


def test_compare_independent_skips_joined_model(tmp_path: Path) -> None:
    report = _write_local(tmp_path / "Sales.Report")
    _write_model(tmp_path / "Sales.SemanticModel", body="model Changed\n")
    results = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), report),  # type: ignore[arg-type]
        independent=True,
    )
    assert len(results) == 1
    assert results[0].ok and results[0].identical
    assert not results[0].messages


def test_compare_joined_unbound_notes_message(tmp_path: Path) -> None:
    report = _write_local(tmp_path / "Sales.Report")
    _write_model(tmp_path / "Sales.SemanticModel")
    unbound = {
        "format": "PBIR",
        "parts": [
            _part(
                "definition.pbir",
                json.dumps(
                    {
                        "version": "4.0",
                        "datasetReference": {
                            "byPath": {"path": "../Sales.SemanticModel"}
                        },
                    }
                ).encode("utf-8"),
            ),
            _part("definition/report.json", b'{"version": "1.0"}\n'),
        ],
    }
    results = compare_report(
        FakeClient(report_defs={REPORT: unbound}),
        WorkItem(Target(WS, REPORT), report),  # type: ignore[arg-type]
        powerbi_client=FakePowerBi(dataset_id=None),
    )
    assert len(results) == 1
    assert results[0].ok
    assert any("not compared" in m for m in results[0].messages)


def test_compare_joined_origin(tmp_path: Path) -> None:
    del tmp_path
    results = compare_report(
        FakeClient(
            sm_bodies={MODEL: "model Sales\n", ORIGIN_MODEL: "model Sales\n"},
        ),
        WorkItem(Target(WS, REPORT), None, origin=Target(WS, ORIGIN)),  # type: ignore[arg-type]
    )
    assert len(results) == 2
    assert results[0].ok and not results[0].identical
    assert results[1].ok and results[1].identical


def test_run_compare_batch_status_joined(tmp_path: Path, monkeypatch: Any) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: messages.append(msg),
    )
    report_a = _write_local(tmp_path / "A.Report")
    _write_model(tmp_path / "A.SemanticModel")
    report_b = _write_local(tmp_path / "B.Report")
    _write_model(tmp_path / "B.SemanticModel")
    report_id_b = "33333333-3333-3333-3333-333333333333"
    model_id_b = "88888888-8888-8888-8888-888888888888"

    class MultiClient(FakeClient):
        def request(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, Any] | None = None,
            json: Any = None,
            wait: bool = True,
        ) -> Any:
            del params, json, wait
            if (
                method == "POST"
                and "/reports/" in path
                and path.endswith("/getDefinition")
            ):
                item_id = path.split("/")[-2]
                model_id = MODEL if item_id == REPORT else model_id_b
                return {"definition": _definition(model_id=model_id)}
            if (
                method == "POST"
                and "/semanticModels/" in path
                and path.endswith("/getDefinition")
            ):
                item_id = path.split("/")[-2]
                return {"definition": _sm_definition()}
            raise FabricApiError(f"unexpected {method} {path}")

    run_compare_batch(
        MultiClient(sm_bodies={MODEL: "model Sales\n", model_id_b: "model Sales\n"}),
        [
            WorkItem(Target(WS, REPORT), report_a),  # type: ignore[arg-type]
            WorkItem(Target(WS, report_id_b), report_b),  # type: ignore[arg-type]
        ],
    )
    assert messages == [
        "1 of 4 · Comparing report (Sales)…",
        "2 of 4 · Comparing semantic model (Sales)…",
        "3 of 4 · Comparing report (Sales)…",
        "4 of 4 · Comparing semantic model (Sales)…",
    ]


def test_run_compare_batch_status_independent(tmp_path: Path, monkeypatch: Any) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: messages.append(msg),
    )
    report = _write_local(tmp_path / "Sales.Report")
    _write_model(tmp_path / "Sales.SemanticModel")
    run_compare_batch(
        FakeClient(),
        [WorkItem(Target(WS, REPORT), report)],  # type: ignore[arg-type]
        independent=True,
    )
    assert messages == ["1 of 1 · Comparing report (Sales)…"]


def test_run_compare_batch_status_skipped_join(
    tmp_path: Path, monkeypatch: Any
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: messages.append(msg),
    )
    report_a = _write_local(tmp_path / "A.Report")
    _write_model(tmp_path / "A.SemanticModel")
    report_b = _write_local(tmp_path / "B.Report")
    _write_model(tmp_path / "B.SemanticModel")
    report_id_b = "33333333-3333-3333-3333-333333333333"
    unbound = {
        "format": "PBIR",
        "parts": [
            _part(
                "definition.pbir",
                json.dumps(
                    {
                        "version": "4.0",
                        "datasetReference": {"byPath": {"path": "../A.SemanticModel"}},
                    }
                ).encode("utf-8"),
            ),
            _part("definition/report.json", b'{"version": "1.0"}\n'),
        ],
    }

    class MixedClient(FakeClient):
        def request(
            self,
            method: str,
            path: str,
            *,
            params: dict[str, Any] | None = None,
            json: Any = None,
            wait: bool = True,
        ) -> Any:
            del params, json, wait
            if (
                method == "POST"
                and "/reports/" in path
                and path.endswith("/getDefinition")
            ):
                item_id = path.split("/")[-2]
                if item_id == REPORT:
                    return {"definition": unbound}
                return {"definition": _definition()}
            if (
                method == "POST"
                and "/semanticModels/" in path
                and path.endswith("/getDefinition")
            ):
                return {"definition": _sm_definition()}
            raise FabricApiError(f"unexpected {method} {path}")

    run_compare_batch(
        MixedClient(),
        [
            WorkItem(Target(WS, REPORT), report_a),  # type: ignore[arg-type]
            WorkItem(Target(WS, report_id_b), report_b),  # type: ignore[arg-type]
        ],
        powerbi_client=FakePowerBi(dataset_id=None),
    )
    assert messages == [
        "1 of 4 · Comparing report (Sales)…",
        "2 of 3 · Comparing report (Sales)…",
        "3 of 3 · Comparing semantic model (Sales)…",
    ]
