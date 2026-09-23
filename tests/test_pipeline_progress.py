"""Tests for pipeline run activity progress (spinner detail)."""

from __future__ import annotations

import base64
import json
from typing import Any

from fabric_tools.client import ItemJobStart
from fabric_tools.parsing import Target
from fabric_tools.pipeline.progress import (
    activity_progress,
    pipeline_progress,
    top_level_activity_names,
)

WS = "11111111-1111-1111-1111-111111111111"
PIPE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

CONTENT = {
    "properties": {
        "activities": [
            {"name": "Wait1", "type": "Wait"},
            {
                "name": "ForEachTable",
                "type": "ForEach",
                "typeProperties": {"activities": [{"name": "CopyTable"}]},
            },
            {"name": "Notify", "type": "WebActivity"},
            {"name": "Wait1", "type": "Wait"},
            {"type": "Wait"},
        ]
    }
}


def _run(name: str, status: str, start: str) -> dict[str, Any]:
    return {"activityName": name, "status": status, "activityRunStart": start}


def test_top_level_activity_names_dedupes_and_skips_nested() -> None:
    assert top_level_activity_names(CONTENT) == ["Wait1", "ForEachTable", "Notify"]


def test_top_level_activity_names_handles_missing_properties() -> None:
    assert top_level_activity_names({}) == []
    assert top_level_activity_names({"properties": {"activities": "nope"}}) == []


def test_activity_progress_none_before_any_run() -> None:
    assert activity_progress(["Wait1"], []) is None


def test_activity_progress_prefers_latest_in_progress() -> None:
    names = ["Wait1", "ForEachTable", "Notify"]
    runs = [
        _run("ForEachTable", "InProgress", "2026-01-01T00:00:02Z"),
        _run("Wait1", "Succeeded", "2026-01-01T00:00:01Z"),
        _run("CopyTable", "InProgress", "2026-01-01T00:00:03Z"),
        _run("CopyTable", "Succeeded", "2026-01-01T00:00:04Z"),
    ]

    assert activity_progress(names, runs) == "2/3 CopyTable"


def test_activity_progress_falls_back_to_latest_started() -> None:
    runs = [
        _run("Wait1", "Succeeded", "2026-01-01T00:00:01Z"),
        _run("Notify", "Succeeded", "2026-01-01T00:00:05Z"),
    ]

    assert activity_progress(["Wait1", "Notify"], runs) == "2/2 Notify"


def test_activity_progress_without_definition_names_shows_current_only() -> None:
    runs = [_run("Copy1", "InProgress", "2026-01-01T00:00:01Z")]

    assert activity_progress([], runs) == "Copy1"


class FakeClient:
    def __init__(self, runs: list[dict[str, Any]]) -> None:
        self.runs = runs
        self.definition_calls = 0
        self.queries: list[dict[str, str]] = []

    def request(self, method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        assert method == "POST"
        assert path.endswith(f"/dataPipelines/{PIPE}/getDefinition")
        self.definition_calls += 1
        payload = base64.b64encode(json.dumps(CONTENT).encode()).decode()
        return {
            "definition": {
                "parts": [
                    {
                        "path": "pipeline-content.json",
                        "payload": payload,
                        "payloadType": "InlineBase64",
                    }
                ]
            }
        }

    def query_pipeline_activity_runs(
        self,
        workspace_id: str,
        job_instance_id: str,
        *,
        updated_after: str,
        updated_before: str,
    ) -> list[dict[str, Any]]:
        self.queries.append(
            {
                "workspace_id": workspace_id,
                "job_instance_id": job_instance_id,
                "updated_after": updated_after,
                "updated_before": updated_before,
            }
        )
        return self.runs


def _job(job_instance_id: str | None = "job-1") -> ItemJobStart:
    return ItemJobStart(
        workspace_id=WS,
        item_id=PIPE,
        job_type="Pipeline",
        job_instance_id=job_instance_id,
        location=None,
        retry_after=1,
    )


def test_pipeline_progress_reads_definition_once_and_queries_each_poll() -> None:
    client = FakeClient([_run("Wait1", "InProgress", "2026-01-01T00:00:01Z")])

    detail = pipeline_progress(client, Target(WS, PIPE), _job())

    assert detail({"status": "InProgress"}) == "1/3 Wait1"
    assert detail({"status": "InProgress"}) == "1/3 Wait1"
    assert client.definition_calls == 1
    assert len(client.queries) == 2
    query = client.queries[0]
    assert query["workspace_id"] == WS
    assert query["job_instance_id"] == "job-1"
    assert query["updated_after"].endswith("Z")
    assert query["updated_after"] < query["updated_before"]


def test_pipeline_progress_without_job_instance_id_is_noop() -> None:
    client = FakeClient([])

    detail = pipeline_progress(client, Target(WS, PIPE), _job(job_instance_id=None))

    assert detail({"status": "InProgress"}) is None
    assert client.definition_calls == 0
