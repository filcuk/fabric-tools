"""Tests for FabricClient list pagination with mocked HTTP."""

from __future__ import annotations

import httpx
import pytest

from fabric_tools.client import FabricApiError, FabricClient

WS = "11111111-1111-1111-1111-111111111111"


def _client(mock_transport: httpx.MockTransport) -> FabricClient:
    return FabricClient(
        get_token=lambda: "test-token",
        client=httpx.Client(transport=mock_transport),
        sleep=lambda _seconds: None,
    )


def test_list_workspaces_single_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/workspaces")
        assert "continuationToken" not in request.url.params
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": WS,
                        "displayName": "My workspace",
                        "type": "Personal",
                    }
                ]
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        rows = client.list_workspaces()
    assert len(rows) == 1
    assert rows[0]["displayName"] == "My workspace"


def test_list_workspaces_follows_continuation_token() -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/workspaces")
        token = request.url.params.get("continuationToken")
        calls.append(token)
        if token is None:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "type": "Workspace",
                        }
                    ],
                    "continuationToken": "page-2",
                },
            )
        assert token == "page-2"
        return httpx.Response(
            200,
            json={
                "value": [
                    {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "type": "Personal"}
                ]
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        rows = client.list_workspaces()
    assert calls == [None, "page-2"]
    assert [r["id"] for r in rows] == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ]


def test_list_items_passes_type_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/workspaces/{WS}/items")
        assert request.url.params.get("type") == "Notebook"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "displayName": "ETL",
                        "type": "Notebook",
                    }
                ]
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        rows = client.list_items(WS, type="Notebook")
    assert len(rows) == 1
    assert rows[0]["type"] == "Notebook"


def test_list_items_paginates() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.path.endswith(f"/workspaces/{WS}/items")
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "value": [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}],
                    "continuationToken": "next",
                },
            )
        assert request.url.params.get("continuationToken") == "next"
        return httpx.Response(
            200,
            json={"value": [{"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}]},
        )

    with _client(httpx.MockTransport(handler)) as client:
        rows = client.list_items(WS)
    assert len(rows) == 2


def test_list_paginated_rejects_non_list_value() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": "oops"})

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(FabricApiError, match="not a list"):
            client.list_workspaces()
