"""Tests for PowerBiClient with mocked HTTP."""

from __future__ import annotations

import httpx
import pytest

from fabric_tools.powerbi_client import (
    PowerBiApiError,
    PowerBiClient,
    dataflow_id_from_import,
)


def _client(mock_transport: httpx.MockTransport) -> PowerBiClient:
    return PowerBiClient(
        get_token=lambda: "test-token",
        client=httpx.Client(transport=mock_transport),
        sleep=lambda _seconds: None,
    )


def test_get_group_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.path.endswith("/groups/ws-1")
        return httpx.Response(200, json={"id": "ws-1", "name": "Dev"})

    with _client(httpx.MockTransport(handler)) as client:
        data = client.get_group("ws-1")
    assert data["name"] == "Dev"


def test_list_and_get_dataflow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/groups/ws-1/dataflows")
        return httpx.Response(
            200,
            json={
                "value": [
                    {"objectId": "df-1", "name": "Sales"},
                    {"objectId": "df-2", "name": "Finance"},
                ]
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        items = client.list_dataflows("ws-1")
        assert len(items) == 2
        found = client.get_dataflow("ws-1", "df-2")
    assert found["name"] == "Finance"


def test_get_dataflow_not_found() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": []})

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(PowerBiApiError, match="not found") as exc_info:
            client.get_dataflow("ws-1", "missing")
    assert exc_info.value.status_code == 404


def test_get_dataflow_definition() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/groups/ws-1/dataflows/df-1")
        return httpx.Response(
            200,
            json={"name": "Sales", "entities": [{"name": "Query1"}]},
        )

    with _client(httpx.MockTransport(handler)) as client:
        model = client.get_dataflow_definition("ws-1", "df-1")
    assert model["name"] == "Sales"
    assert model["entities"][0]["name"] == "Query1"


def test_delete_dataflow() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        assert request.method == "DELETE"
        assert request.url.path.endswith("/groups/ws-1/dataflows/df-1")
        return httpx.Response(200)

    with _client(httpx.MockTransport(handler)) as client:
        client.delete_dataflow("ws-1", "df-1")
    assert calls == ["DELETE"]


def test_create_dataflow_from_model_polls_until_succeeded() -> None:
    calls = {"n": 0}
    model_bytes = b'{"name":"Sales","entities":[]}'

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.method == "POST" and request.url.path.endswith("/imports"):
            assert request.url.params["datasetDisplayName"] == "model.json"
            assert request.url.params["nameConflict"] == "Abort"
            assert "multipart/form-data" in request.headers["Content-Type"]
            return httpx.Response(
                202, json={"id": "imp-1", "importState": "Publishing"}
            )
        if request.method == "GET" and request.url.path.endswith("/imports/imp-1"):
            if calls["n"] < 3:
                return httpx.Response(
                    200,
                    json={"id": "imp-1", "importState": "Publishing"},
                )
            return httpx.Response(
                200,
                json={
                    "id": "imp-1",
                    "importState": "Succeeded",
                    "dataflows": [{"objectId": "df-new", "name": "Sales"}],
                },
            )
        return httpx.Response(
            404, json={"error": {"message": f"unexpected {request.url}"}}
        )

    with _client(httpx.MockTransport(handler)) as client:
        result = client.create_dataflow_from_model("ws-1", model_bytes)
    assert result["importState"] == "Succeeded"
    assert dataflow_id_from_import(result) == "df-new"


def test_create_dataflow_import_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "imp-fail"})
        return httpx.Response(
            200,
            json={
                "id": "imp-fail",
                "importState": "Failed",
                "error": {
                    "code": "Conflict",
                    "details": [{"message": "Dataflow already exists"}],
                },
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(PowerBiApiError, match="already exists") as exc_info:
            client.create_dataflow_from_model("ws-1", b"{}")
    assert exc_info.value.error_code == "Conflict"


def test_http_error_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "PowerBIEntityNotFound",
                    "message": "missing group",
                }
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(PowerBiApiError, match="missing group") as exc_info:
            client.get_group("missing")
    assert exc_info.value.error_code == "PowerBIEntityNotFound"


def test_wait_for_import_updates_activity_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.powerbi_client.update_status",
        lambda msg: messages.append(msg),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"id": "imp-1"})
        return httpx.Response(
            200,
            json={"id": "imp-1", "importState": "Succeeded", "dataflows": []},
        )

    with _client(httpx.MockTransport(handler)) as client:
        client.create_dataflow_from_model("ws-1", b"{}")

    assert messages == ["Waiting for Power BI import (imp-1)..."]


def test_dataflow_id_from_import_fallbacks() -> None:
    assert dataflow_id_from_import({"dataflows": [{"id": "a"}]}) == "a"
    assert dataflow_id_from_import({"dataflows": [{"targetDataflowId": "b"}]}) == "b"
    assert dataflow_id_from_import({"dataflows": []}) is None
    assert dataflow_id_from_import({}) is None
