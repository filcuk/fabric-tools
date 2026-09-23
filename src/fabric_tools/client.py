"""Microsoft Fabric REST API client with LRO support."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from fabric_tools.auth import TokenProvider, token_provider
from fabric_tools.status import set_percent

DEFAULT_BASE_URL = "https://api.fabric.microsoft.com/v1"
DEFAULT_RETRY_AFTER_SECONDS = 5
TERMINAL_STATUSES = frozenset({"Succeeded", "Failed", "Canceled"})
JOB_STATUS_COMPLETED = "Completed"
JOB_FAILED_STATUSES = frozenset({"Failed", "Cancelled", "Canceled", "Deduped"})


class FabricApiError(Exception):
    """Raised when a Fabric API call or LRO fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id
        self.details = details

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.error_code:
            parts.append(f"errorCode={self.error_code}")
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.request_id:
            parts.append(f"requestId={self.request_id}")
        return " | ".join(parts)


@dataclass(frozen=True)
class ItemJobStart:
    """Accepted on-demand item job (Job Scheduler 202 response)."""

    workspace_id: str
    item_id: str
    job_type: str
    job_instance_id: str | None
    location: str | None
    retry_after: int


class FabricClient:
    """Thin httpx wrapper around the Fabric Core REST API."""

    def __init__(
        self,
        *,
        get_token: TokenProvider | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self._get_token = get_token or token_provider()
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> FabricClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def ensure_authenticated(self) -> None:
        """Acquire a token now so the first API call is not the first auth wait."""
        self._get_token()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        """Send a request. When ``wait`` is True, poll LROs to completion."""
        response = self._send(method, path, params=params, json=json)
        if wait and response.status_code == 202:
            return self.wait_for_operation(response)
        if response.status_code in (200, 201):
            return self._json_or_none(response)
        if response.status_code == 202:
            return {
                "status": "Accepted",
                "operationId": response.headers.get("x-ms-operation-id"),
                "location": response.headers.get("Location"),
            }
        self._raise_api_error(response)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        return self._client.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json,
        )

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        """GET /workspaces/{workspaceId}."""
        result = self.request("GET", f"/workspaces/{workspace_id}")
        if not isinstance(result, dict):
            raise FabricApiError("Unexpected empty workspace response")
        return result

    def list_workspaces(self) -> list[dict[str, Any]]:
        """GET /workspaces (all pages via continuationToken)."""
        return self._list_paginated("/workspaces")

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        """GET /workspaces/{workspaceId}/items/{itemId}."""
        result = self.request("GET", f"/workspaces/{workspace_id}/items/{item_id}")
        if not isinstance(result, dict):
            raise FabricApiError("Unexpected empty item response")
        return result

    def list_items(
        self,
        workspace_id: str,
        *,
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /workspaces/{workspaceId}/items (all pages; optional ``type`` filter)."""
        params: dict[str, Any] | None = None
        if type is not None and type != "":
            params = {"type": type}
        return self._list_paginated(
            f"/workspaces/{workspace_id}/items",
            params=params,
        )

    def run_dataflow_apply_changes(
        self,
        workspace_id: str,
        dataflow_id: str,
    ) -> Any:
        """POST Dataflow Apply Changes job and wait (UI Save / publish for refresh).

        Uses ``/dataflows/{id}/jobs/applyChanges/instances``. Requires user
        identity today (service principal is not supported by this Fabric API).
        """
        return self.request(
            "POST",
            f"/workspaces/{workspace_id}/dataflows/{dataflow_id}"
            "/jobs/applyChanges/instances",
        )

    def run_on_demand_item_job(
        self,
        workspace_id: str,
        item_id: str,
        job_type: str,
        *,
        execution_data: dict[str, Any] | None = None,
    ) -> ItemJobStart:
        """POST /workspaces/{ws}/items/{id}/jobs/{jobType}/instances (no wait).

        Returns the accepted job; poll it with :meth:`wait_for_item_job`.
        """
        body = {"executionData": execution_data} if execution_data else None
        response = self._send(
            "POST",
            f"/workspaces/{workspace_id}/items/{item_id}/jobs/{job_type}/instances",
            json=body,
        )
        if response.status_code not in (200, 201, 202):
            self._raise_api_error(response)
        location = response.headers.get("Location") or None
        return ItemJobStart(
            workspace_id=workspace_id,
            item_id=item_id,
            job_type=job_type,
            job_instance_id=_job_instance_id_from_location(location),
            location=location,
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
        )

    def get_item_job_instance(
        self,
        workspace_id: str,
        item_id: str,
        job_instance_id: str,
    ) -> dict[str, Any]:
        """GET /workspaces/{ws}/items/{id}/jobs/instances/{jobInstanceId}."""
        result = self.request(
            "GET",
            f"/workspaces/{workspace_id}/items/{item_id}"
            f"/jobs/instances/{job_instance_id}",
        )
        if not isinstance(result, dict):
            raise FabricApiError("Unexpected empty job instance response")
        return result

    def wait_for_item_job(
        self,
        job: ItemJobStart,
        *,
        on_poll: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Poll an item job instance until ``Completed``; raise on failure.

        *on_poll* receives each non-terminal job instance payload (progress hooks).
        ``Failed`` / ``Cancelled`` / ``Deduped`` raise :class:`FabricApiError`.
        """
        if job.job_instance_id:
            state_url = (
                f"{self.base_url}/workspaces/{job.workspace_id}/items/{job.item_id}"
                f"/jobs/instances/{job.job_instance_id}"
            )
        elif job.location:
            state_url = job.location
        else:
            raise FabricApiError(
                "Job response missing Location header; cannot poll job status",
                status_code=202,
            )

        retry_after = job.retry_after
        while True:
            self._sleep(retry_after)
            response = self._client.get(state_url, headers=self._headers())
            retry_after = _parse_retry_after(
                response.headers.get("Retry-After"),
                default=DEFAULT_RETRY_AFTER_SECONDS,
            )
            if response.status_code != 200:
                self._raise_api_error(response)
            payload = self._json_or_none(response)
            if not isinstance(payload, dict):
                raise FabricApiError("Unexpected empty job instance response")

            status = payload.get("status")
            if status == JOB_STATUS_COMPLETED:
                return payload
            if status in JOB_FAILED_STATUSES:
                raise _job_failure_error(payload, status)
            if on_poll is not None:
                on_poll(payload)

    def query_pipeline_activity_runs(
        self,
        workspace_id: str,
        job_instance_id: str,
        *,
        updated_after: str,
        updated_before: str,
    ) -> list[dict[str, Any]]:
        """POST .../datapipelines/pipelineruns/{jobInstanceId}/queryactivityruns.

        *updated_after* / *updated_before* are ISO-8601 UTC timestamps. Collects
        all pages; accepts both a bare list and a ``value`` + token envelope.
        """
        path = (
            f"/workspaces/{workspace_id}/datapipelines/pipelineruns"
            f"/{job_instance_id}/queryactivityruns"
        )
        body: dict[str, Any] = {
            "filters": [],
            "orderBy": [{"orderBy": "ActivityRunStart", "order": "ASC"}],
            "lastUpdatedAfter": updated_after,
            "lastUpdatedBefore": updated_before,
        }
        runs: list[dict[str, Any]] = []
        while True:
            result = self.request("POST", path, json=body, wait=False)
            if isinstance(result, list):
                runs.extend(entry for entry in result if isinstance(entry, dict))
                break
            if not isinstance(result, dict):
                break
            page = result.get("value")
            if isinstance(page, list):
                runs.extend(entry for entry in page if isinstance(entry, dict))
            token = result.get("continuationToken")
            if not token or not isinstance(token, str):
                break
            body = {**body, "continuationToken": token}
        return runs

    def _list_paginated(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect all ``value`` entries across Fabric continuationToken pages."""
        items: list[dict[str, Any]] = []
        query: dict[str, Any] = dict(params) if params else {}
        while True:
            result = self.request("GET", path, params=query or None)
            if not isinstance(result, dict):
                raise FabricApiError(f"Unexpected empty list response for {path}")
            page = result.get("value")
            if page is None:
                page = []
            if not isinstance(page, list):
                raise FabricApiError(
                    f"Unexpected list response for {path}: value is not a list"
                )
            for entry in page:
                if isinstance(entry, dict):
                    items.append(entry)
                else:
                    raise FabricApiError(
                        f"Unexpected list entry for {path}: expected object"
                    )
            token = result.get("continuationToken")
            if not token or not isinstance(token, str):
                break
            query = dict(params) if params else {}
            query["continuationToken"] = token
        return items

    def wait_for_operation(self, response: httpx.Response) -> Any:
        """Poll a 202 Accepted response until the LRO finishes; return result body."""
        if response.status_code in (200, 201):
            return self._json_or_none(response)
        if response.status_code != 202:
            self._raise_api_error(response)

        operation_id = response.headers.get("x-ms-operation-id")
        location = response.headers.get("Location")
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))

        if not location and not operation_id:
            raise FabricApiError(
                "LRO response missing Location and x-ms-operation-id headers",
                status_code=202,
            )

        state_url = location or f"{self.base_url}/operations/{operation_id}"

        try:
            return self._poll_operation(state_url, operation_id, retry_after)
        finally:
            set_percent(None)

    def _poll_operation(
        self,
        state_url: str,
        operation_id: str | None,
        retry_after: int,
    ) -> Any:
        while True:
            self._sleep(retry_after)
            state_response = self._client.get(state_url, headers=self._headers())
            retry_after = _parse_retry_after(
                state_response.headers.get("Retry-After"),
                default=retry_after,
            )

            if state_response.status_code not in (200, 201):
                self._raise_api_error(state_response)

            payload = self._json_or_none(state_response)
            status = _operation_status(payload)

            # Some Location URLs eventually return the final resource (no status field).
            if status is None:
                return payload

            if status == "Succeeded":
                return self._fetch_operation_result(
                    operation_id, state_response, payload
                )

            if status in {"Failed", "Canceled"}:
                error = (
                    (payload or {}).get("error") if isinstance(payload, dict) else None
                )
                message = "Fabric long-running operation failed"
                error_code = None
                if isinstance(error, dict):
                    message = error.get("message") or message
                    error_code = error.get("errorCode") or error.get("code")
                raise FabricApiError(
                    message,
                    status_code=state_response.status_code,
                    error_code=error_code,
                    request_id=(payload or {}).get("requestId")
                    if isinstance(payload, dict)
                    else None,
                    details=error or payload,
                )

            percent = _operation_percent(payload)
            if percent is not None:
                set_percent(percent)

            # Still running — prefer Location from latest response when present.
            next_location = state_response.headers.get("Location")
            if next_location:
                state_url = next_location

    def _fetch_operation_result(
        self,
        operation_id: str | None,
        state_response: httpx.Response,
        state_payload: Any,
    ) -> Any:
        result_url = None
        if operation_id:
            result_url = f"{self.base_url}/operations/{operation_id}/result"
        else:
            # Fall back to Location if it now points at a result resource.
            result_url = state_response.headers.get("Location")

        if not result_url:
            return state_payload

        result_response = self._client.get(result_url, headers=self._headers())
        if result_response.status_code == 404:
            # Some LROs have no result payload.
            return state_payload
        if result_response.status_code not in (200, 201):
            self._raise_api_error(result_response)
        return self._json_or_none(result_response)

    @staticmethod
    def _json_or_none(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise FabricApiError(
                "Response was not valid JSON",
                status_code=response.status_code,
                details=response.text,
            ) from exc

    @staticmethod
    def _raise_api_error(response: httpx.Response) -> None:
        error_code = None
        message = f"Fabric API request failed with HTTP {response.status_code}"
        request_id = None
        details: Any = None
        try:
            details = response.json()
        except ValueError:
            details = response.text or None
        if isinstance(details, dict):
            message = details.get("message") or message
            error_code = details.get("errorCode")
            request_id = details.get("requestId")
        raise FabricApiError(
            message,
            status_code=response.status_code,
            error_code=error_code,
            request_id=request_id,
            details=details,
        )


def _parse_retry_after(
    value: str | None,
    *,
    default: int = DEFAULT_RETRY_AFTER_SECONDS,
) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(parsed, 1)


def _job_instance_id_from_location(location: str | None) -> str | None:
    """Last path segment after ``/jobs/instances/`` (``None`` when absent)."""
    if not location:
        return None
    segments = [part for part in urlparse(location).path.split("/") if part]
    if len(segments) >= 2 and segments[-2].lower() == "instances":
        return segments[-1]
    return None


def _job_failure_error(payload: dict[str, Any], status: str) -> FabricApiError:
    reason = payload.get("failureReason")
    message = f"Fabric job {status.lower()}"
    error_code = None
    request_id = None
    if status == "Deduped":
        message = "Fabric job skipped: another run of this job type is in progress"
        error_code = "Deduped"
    if isinstance(reason, dict):
        message = reason.get("message") or message
        error_code = reason.get("errorCode") or error_code
        request_id = reason.get("requestId")
    return FabricApiError(
        message,
        error_code=error_code,
        request_id=request_id,
        details=payload,
    )


def _operation_percent(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("percentComplete")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return min(max(value, 0), 100)


def _operation_status(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if isinstance(status, str):
        return status
    return None
