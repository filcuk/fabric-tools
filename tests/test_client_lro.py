"""Tests for FabricClient LRO handling with mocked HTTP."""

from __future__ import annotations

import httpx
import pytest

from fabric_tools.client import FabricApiError, FabricClient


def _client(mock_transport: httpx.MockTransport) -> FabricClient:
    return FabricClient(
        get_token=lambda: "test-token",
        client=httpx.Client(transport=mock_transport),
        sleep=lambda _seconds: None,
    )


def test_get_workspace_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.path.endswith("/workspaces/ws-1")
        return httpx.Response(200, json={"id": "ws-1", "displayName": "Dev"})

    with _client(httpx.MockTransport(handler)) as client:
        data = client.get_workspace("ws-1")
    assert data["displayName"] == "Dev"


def test_lro_polls_until_succeeded() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.method == "POST" and request.url.path.endswith("/getDefinition"):
            return httpx.Response(
                202,
                headers={
                    "Location": "https://api.fabric.microsoft.com/v1/operations/op-1",
                    "x-ms-operation-id": "op-1",
                    "Retry-After": "1",
                },
            )
        if request.url.path.endswith("/operations/op-1"):
            if calls["n"] < 3:
                return httpx.Response(200, json={"status": "Running"})
            return httpx.Response(200, json={"status": "Succeeded", "error": None})
        if request.url.path.endswith("/operations/op-1/result"):
            return httpx.Response(
                200,
                json={"definition": {"format": "ipynb", "parts": []}},
            )
        return httpx.Response(404, json={"message": f"unexpected {request.url}"})

    with _client(httpx.MockTransport(handler)) as client:
        result = client.request(
            "POST",
            "/workspaces/ws/notebooks/nb/getDefinition",
            params={"format": "ipynb"},
        )
    assert result["definition"]["format"] == "ipynb"


def test_lro_failed_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={
                    "Location": "https://api.fabric.microsoft.com/v1/operations/op-fail",
                    "x-ms-operation-id": "op-fail",
                    "Retry-After": "1",
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "Failed",
                "error": {"errorCode": "Boom", "message": "nope"},
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(FabricApiError, match="nope") as exc_info:
            client.request("POST", "/workspaces/ws/notebooks/nb/updateDefinition")
    assert exc_info.value.error_code == "Boom"


def test_http_error_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "errorCode": "ItemNotFound",
                "message": "missing",
                "requestId": "req-1",
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(FabricApiError, match="missing") as exc_info:
            client.get_item("ws", "item")
    assert exc_info.value.error_code == "ItemNotFound"
    assert exc_info.value.request_id == "req-1"


def test_lro_does_not_overwrite_activity_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: messages.append(msg),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={
                    "Location": "https://api.fabric.microsoft.com/v1/operations/op-1",
                    "x-ms-operation-id": "op-1",
                    "Retry-After": "1",
                },
            )
        if request.url.path.endswith("/operations/op-1"):
            return httpx.Response(200, json={"status": "Succeeded"})
        if request.url.path.endswith("/operations/op-1/result"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    with _client(httpx.MockTransport(handler)) as client:
        client.request("POST", "/workspaces/ws/notebooks/nb/getDefinition")

    assert messages == []
