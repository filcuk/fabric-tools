"""Live activity progress for a running DataPipeline job (spinner detail)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fabric_tools.pipeline.definition import CONTENT_PART, part_payloads

if TYPE_CHECKING:
    from fabric_tools.client import FabricClient, ItemJobStart
    from fabric_tools.parsing import Target

# Activity runs are filtered by last-updated time; start the window a little
# before the job was accepted so clock skew does not hide early activities.
_QUERY_WINDOW_LEAD = timedelta(minutes=5)
_QUERY_WINDOW_TAIL = timedelta(days=1)


def top_level_activity_names(content: dict[str, Any]) -> list[str]:
    """Unique top-level activity names from ``pipeline-content.json`` (in order).

    Nested activities (ForEach / If / Until / Switch bodies) are not counted:
    they may run many times or not at all, so the total would never settle.
    """
    properties = content.get("properties")
    activities = properties.get("activities") if isinstance(properties, dict) else None
    if not isinstance(activities, list):
        return []
    names: list[str] = []
    for activity in activities:
        name = activity.get("name") if isinstance(activity, dict) else None
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def activity_progress(names: list[str], runs: list[dict[str, Any]]) -> str | None:
    """Spinner detail such as ``3/12 CopyCustomers`` (``None`` before any run).

    The count is top-level *names* that have started; the label is the most
    recently started in-progress activity (any depth), else the latest started.
    """
    started = [run for run in runs if isinstance(run.get("activityName"), str)]
    if not started:
        return None
    started.sort(key=lambda run: str(run.get("activityRunStart") or ""))
    in_progress = [run for run in started if run.get("status") == "InProgress"]
    current = str((in_progress or started)[-1]["activityName"])
    if not names:
        return current
    seen = {str(run["activityName"]) for run in started}
    done = sum(1 for name in names if name in seen)
    return f"{done}/{len(names)} {current}"


def pipeline_progress(
    client: FabricClient,
    target: Target,
    job: ItemJobStart,
) -> Callable[[dict[str, Any]], str | None]:
    """Build a job poll hook returning activity progress for the spinner.

    Reads the pipeline definition once for the activity total; each poll then
    queries activity runs for this job instance.
    """
    from fabric_tools.pipeline.ops import get_pipeline_definition

    job_instance_id = job.job_instance_id
    if not job_instance_id or target.item_id is None:
        return lambda _payload: None

    definition = get_pipeline_definition(client, target.workspace_id, target.item_id)
    content_bytes = part_payloads(definition).get(CONTENT_PART)
    content = json.loads(content_bytes) if content_bytes else {}
    names = top_level_activity_names(content if isinstance(content, dict) else {})
    updated_after = _iso_utc(datetime.now(UTC) - _QUERY_WINDOW_LEAD)

    def detail(_payload: dict[str, Any]) -> str | None:
        runs = client.query_pipeline_activity_runs(
            target.workspace_id,
            job_instance_id,
            updated_after=updated_after,
            updated_before=_iso_utc(datetime.now(UTC) + _QUERY_WINDOW_TAIL),
        )
        return activity_progress(names, runs)

    return detail


def _iso_utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
