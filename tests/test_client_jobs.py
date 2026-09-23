"""Tests for Fabric Job Scheduler and Power BI dataset refresh client helpers."""

from __future__ import annotations

import json

import httpx
import pytest

from fabric_tools.client import FabricApiError, FabricClient, ItemJobStart
from fabric_tools.powerbi_client import (
    DatasetRefreshStart,
    PowerBiApiError,
    PowerBiClient,
)

_JOB_LOCATION = (
    "https://api.fabric.microsoft.com/v1/workspaces/ws-1/items/it-1"
    "/jobs/instances/job-1"
)


def _fabric(handler) -> FabricClient:
    return FabricClient(
        get_token=lambda: "test-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )


def _powerbi(handler) -> PowerBiClient:
    return PowerBiClient(
        get_token=lambda: "test-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )


def _job(**overrides) -> ItemJobStart:
    values = {
        "workspace_id": "ws-1",
        "item_id": "it-1",
        "job_type": "Pipeline",
        "job_instance_id": "job-1",
        "location": _JOB_LOCATION,
        "retry_after": 1,
    }
    values.update(overrides)
    return ItemJobStart(**values)


def test_run_on_demand_item_job_parses_location() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(
            202, headers={"Location": _JOB_LOCATION, "Retry-After": "30"}
        )

    with _fabric(handler) as client:
        job = client.run_on_demand_item_job("ws-1", "it-1", "RunNotebook")

    assert seen["method"] == "POST"
    assert seen["path"].endswith(
        "/workspaces/ws-1/items/it-1/jobs/RunNotebook/instances"
    )
    assert seen["body"] == b""
    assert job.job_instance_id == "job-1"
    assert job.location == _JOB_LOCATION
    assert job.retry_after == 30


def test_run_on_demand_item_job_sends_execution_data() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(202, headers={"Location": _JOB_LOCATION})

    with _fabric(handler) as client:
        client.run_on_demand_item_job(
            "ws-1",
            "it-1",
            "Refresh",
            execution_data={"executeOption": "ApplyChangesIfNeeded"},
        )

    assert seen["body"] == {"executionData": {"executeOption": "ApplyChangesIfNeeded"}}


def test_run_on_demand_item_job_location_without_instance_id() -> None:
    location = (
        "https://api.fabric.microsoft.com/v1/workspaces/ws-1/items/it-1"
        "/jobs/instances?jobType=Execute"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, headers={"Location": location})

    with _fabric(handler) as client:
        job = client.run_on_demand_item_job("ws-1", "it-1", "Execute")

    assert job.job_instance_id is None
    assert job.location == location


def test_run_on_demand_item_job_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"errorCode": "InvalidJobType", "message": "bad job"}
        )

    with _fabric(handler) as client, pytest.raises(FabricApiError) as exc_info:
        client.run_on_demand_item_job("ws-1", "it-1", "Nope")

    assert exc_info.value.error_code == "InvalidJobType"


def test_wait_for_item_job_polls_until_completed() -> None:
    statuses = iter(["NotStarted", "InProgress", "Completed"])
    polled: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/jobs/instances/job-1")
        return httpx.Response(200, json={"id": "job-1", "status": next(statuses)})

    with _fabric(handler) as client:
        result = client.wait_for_item_job(
            _job(), on_poll=lambda payload: polled.append(payload["status"])
        )

    assert result["status"] == "Completed"
    assert polled == ["NotStarted", "InProgress"]


def test_wait_for_item_job_uses_location_without_instance_id() -> None:
    location = "https://api.fabric.microsoft.com/v1/custom/poll"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == location
        return httpx.Response(200, json={"status": "Completed"})

    with _fabric(handler) as client:
        result = client.wait_for_item_job(_job(job_instance_id=None, location=location))

    assert result["status"] == "Completed"


def test_wait_for_item_job_without_location_raises() -> None:
    with (
        _fabric(lambda _r: httpx.Response(500)) as client,
        pytest.raises(FabricApiError, match="missing Location"),
    ):
        client.wait_for_item_job(_job(job_instance_id=None, location=None))


def test_wait_for_item_job_failed_uses_failure_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "Failed",
                "failureReason": {
                    "errorCode": "ActivityFailed",
                    "message": "Copy1 failed",
                    "requestId": "req-9",
                },
            },
        )

    with _fabric(handler) as client, pytest.raises(FabricApiError) as exc_info:
        client.wait_for_item_job(_job())

    assert "Copy1 failed" in str(exc_info.value)
    assert exc_info.value.error_code == "ActivityFailed"
    assert exc_info.value.request_id == "req-9"


def test_wait_for_item_job_deduped_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "Deduped"})

    with _fabric(handler) as client, pytest.raises(FabricApiError) as exc_info:
        client.wait_for_item_job(_job())

    assert exc_info.value.error_code == "Deduped"
    assert "in progress" in str(exc_info.value)


def test_query_pipeline_activity_runs_paginates() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith(
            "/workspaces/ws-1/datapipelines/pipelineruns/job-1/queryactivityruns"
        )
        body = json.loads(request.content)
        bodies.append(body)
        if "continuationToken" not in body:
            return httpx.Response(
                200,
                json={
                    "value": [{"activityName": "Wait1", "status": "Succeeded"}],
                    "continuationToken": "next",
                },
            )
        return httpx.Response(
            200, json={"value": [{"activityName": "Copy1", "status": "InProgress"}]}
        )

    with _fabric(handler) as client:
        runs = client.query_pipeline_activity_runs(
            "ws-1",
            "job-1",
            updated_after="2026-01-01T00:00:00Z",
            updated_before="2026-01-02T00:00:00Z",
        )

    assert [run["activityName"] for run in runs] == ["Wait1", "Copy1"]
    assert bodies[0]["lastUpdatedAfter"] == "2026-01-01T00:00:00Z"
    assert bodies[0]["lastUpdatedBefore"] == "2026-01-02T00:00:00Z"
    assert bodies[1]["continuationToken"] == "next"


def test_query_pipeline_activity_runs_accepts_bare_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"activityName": "Wait1"}, "junk"])

    with _fabric(handler) as client:
        runs = client.query_pipeline_activity_runs(
            "ws-1",
            "job-1",
            updated_after="2026-01-01T00:00:00Z",
            updated_before="2026-01-02T00:00:00Z",
        )

    assert runs == [{"activityName": "Wait1"}]


def test_refresh_dataset_parses_headers() -> None:
    seen: dict[str, object] = {}
    location = (
        "https://api.powerbi.com/v1.0/myorg/groups/ws-1/datasets/ds-1/refreshes/rf-1"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            202, headers={"Location": location, "x-ms-request-id": "req-1"}
        )

    with _powerbi(handler) as client:
        refresh = client.refresh_dataset("ws-1", "ds-1")

    assert seen["path"].endswith("/groups/ws-1/datasets/ds-1/refreshes")
    assert seen["body"] == {"notifyOption": "NoNotification"}
    assert refresh.request_id == "req-1"
    assert refresh.refresh_id == "rf-1"


def test_refresh_dataset_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": "InvalidRequest", "message": "nope"}}
        )

    with _powerbi(handler) as client, pytest.raises(PowerBiApiError) as exc_info:
        client.refresh_dataset("ws-1", "ds-1")

    assert exc_info.value.error_code == "InvalidRequest"


def _refresh(**overrides) -> DatasetRefreshStart:
    values = {
        "group_id": "ws-1",
        "dataset_id": "ds-1",
        "request_id": "req-1",
        "refresh_id": None,
        "location": None,
    }
    values.update(overrides)
    return DatasetRefreshStart(**values)


def test_wait_for_dataset_refresh_matches_request_id() -> None:
    pages = iter(
        [
            [],
            [{"requestId": "req-1", "status": "Unknown"}],
            [
                {"requestId": "other", "status": "Failed"},
                {"requestId": "req-1", "status": "Completed"},
            ],
        ]
    )
    polled: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/groups/ws-1/datasets/ds-1/refreshes")
        return httpx.Response(200, json={"value": next(pages)})

    with _powerbi(handler) as client:
        result = client.wait_for_dataset_refresh(
            _refresh(),
            on_poll=lambda entry: polled.append(entry and entry["status"]),
        )

    assert result["status"] == "Completed"
    assert polled == [None, "Unknown"]


def test_wait_for_dataset_refresh_failed_uses_service_exception() -> None:
    exception = json.dumps(
        {"errorCode": "ModelRefreshFailed", "errorDescription": "Source unreachable"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "requestId": "rf-1",
                        "status": "Failed",
                        "serviceExceptionJson": exception,
                    }
                ]
            },
        )

    with _powerbi(handler) as client, pytest.raises(PowerBiApiError) as exc_info:
        client.wait_for_dataset_refresh(_refresh(request_id=None, refresh_id="rf-1"))

    assert "Source unreachable" in str(exc_info.value)
    assert exc_info.value.error_code == "ModelRefreshFailed"


def test_wait_for_dataset_refresh_without_ids_raises() -> None:
    with (
        _powerbi(lambda _r: httpx.Response(500)) as client,
        pytest.raises(PowerBiApiError, match="missing request id"),
    ):
        client.wait_for_dataset_refresh(_refresh(request_id=None))
