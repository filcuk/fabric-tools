"""Power BI REST API client (Dataflow Gen1, reports, paginated reports)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from fabric_tools.auth import POWER_BI_SCOPE, TokenProvider, token_provider

DEFAULT_BASE_URL = "https://api.powerbi.com/v1.0/myorg"
DEFAULT_RETRY_AFTER_SECONDS = 2
REFRESH_POLL_SECONDS = 5
IMPORT_TERMINAL_STATES = frozenset({"Succeeded", "Failed"})
# Refresh history ``status``: ``Unknown`` means in progress.
REFRESH_FAILED_STATUSES = frozenset({"Failed", "Disabled", "Cancelled", "TimedOut"})


class PowerBiApiError(Exception):
    """Raised when a Power BI API call or import fails."""

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
class DatasetRefreshStart:
    """Accepted semantic model (dataset) refresh request."""

    group_id: str
    dataset_id: str
    request_id: str | None
    refresh_id: str | None
    location: str | None


class PowerBiClient:
    """Thin httpx wrapper around Power BI REST APIs used by fabric-tools."""

    def __init__(
        self,
        *,
        get_token: TokenProvider | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self._get_token = get_token or token_provider(scope=POWER_BI_SCOPE)
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> PowerBiClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def ensure_authenticated(self) -> None:
        """Acquire a token now so the first API call is not the first auth wait."""
        self._get_token()

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
        }

    def _json_headers(self) -> dict[str, str]:
        return {
            **self._auth_headers(),
            "Content-Type": "application/json",
        }

    def get_group(self, group_id: str) -> dict[str, Any]:
        """GET /groups/{groupId} (workspace metadata)."""
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}",
            headers=self._json_headers(),
        )
        if response.status_code != 200:
            self._raise_api_error(response)
        result = self._json_or_none(response)
        if not isinstance(result, dict):
            raise PowerBiApiError("Unexpected empty group response")
        return result

    def list_dataflows(self, group_id: str) -> list[dict[str, Any]]:
        """GET /groups/{groupId}/dataflows."""
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}/dataflows",
            headers=self._json_headers(),
        )
        if response.status_code != 200:
            self._raise_api_error(response)
        result = self._json_or_none(response)
        if not isinstance(result, dict):
            raise PowerBiApiError("Unexpected empty dataflows list response")
        value = result.get("value")
        if not isinstance(value, list):
            raise PowerBiApiError("Dataflows list response missing 'value'")
        return [item for item in value if isinstance(item, dict)]

    def list_reports(self, group_id: str) -> list[dict[str, Any]]:
        """GET /groups/{groupId}/reports."""
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}/reports",
            headers=self._json_headers(),
        )
        if response.status_code != 200:
            self._raise_api_error(response)
        result = self._json_or_none(response)
        if not isinstance(result, dict):
            raise PowerBiApiError("Unexpected empty reports list response")
        value = result.get("value")
        if not isinstance(value, list):
            raise PowerBiApiError("Reports list response missing 'value'")
        return [item for item in value if isinstance(item, dict)]

    def reports_bound_to_dataset(
        self, group_id: str, dataset_id: str
    ) -> list[dict[str, Any]]:
        """Return workspace reports whose ``datasetId`` matches *dataset_id*."""
        return [
            report
            for report in self.list_reports(group_id)
            if str(report.get("datasetId") or "") == dataset_id
        ]

    def get_report(self, group_id: str, report_id: str) -> dict[str, Any]:
        """GET /groups/{groupId}/reports/{reportId}.

        Personal (My) workspaces reject group APIs with ``GroupNotAccessible``;
        those fall back to ``GET /reports/{reportId}``.
        """
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}/reports/{report_id}",
            headers=self._json_headers(),
        )
        if response.status_code != 200 and "GroupNotAccessible" in response.text:
            response = self._client.get(
                f"{self.base_url}/reports/{report_id}",
                headers=self._json_headers(),
            )
        if response.status_code != 200:
            self._raise_api_error(response)
        result = self._json_or_none(response)
        if not isinstance(result, dict):
            raise PowerBiApiError("Unexpected empty report response")
        return result

    def export_report(
        self,
        group_id: str,
        report_id: str,
        *,
        download_type: str = "IncludeModel",
    ) -> bytes:
        """GET /groups/{groupId}/reports/{reportId}/Export — return PBIX bytes.

        *download_type* is ``IncludeModel`` (thick) or ``LiveConnect`` (thin).
        For paginated reports (``.rdl``), use :meth:`export_report_definition`.
        """
        if download_type not in {"IncludeModel", "LiveConnect"}:
            raise ValueError("download_type must be 'IncludeModel' or 'LiveConnect'")
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}/reports/{report_id}/Export",
            headers=self._auth_headers(),
            params={"downloadType": download_type},
        )
        if response.status_code != 200:
            self._raise_api_error(response)
        return response.content

    def export_report_definition(self, group_id: str, report_id: str) -> bytes:
        """GET /groups/{groupId}/reports/{reportId}/Export — return RDL bytes.

        Used for paginated reports. Does not pass ``downloadType`` (PBIX-only).
        """
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}/reports/{report_id}/Export",
            headers=self._auth_headers(),
        )
        if response.status_code != 200:
            self._raise_api_error(response)
        return response.content

    def delete_report(self, group_id: str, report_id: str) -> None:
        """DELETE /groups/{groupId}/reports/{reportId}."""
        response = self._client.delete(
            f"{self.base_url}/groups/{group_id}/reports/{report_id}",
            headers=self._json_headers(),
        )
        if response.status_code not in (200, 204):
            self._raise_api_error(response)

    def import_paginated_report(
        self,
        group_id: str,
        rdl_bytes: bytes,
        *,
        display_name: str,
        name_conflict: str = "Abort",
        wait: bool = True,
    ) -> dict[str, Any]:
        """Import a paginated report ``.rdl`` via POST /groups/{groupId}/imports.

        *name_conflict* is ``Abort`` (create) or ``Overwrite`` (replace by name).
        *display_name* should be the report display name; ``.rdl`` is appended
        when missing. Returns the completed Import object when *wait* is True.
        Use :func:`report_id_from_import` to extract the report id.
        """
        if name_conflict not in {"Abort", "Overwrite"}:
            raise ValueError(
                "name_conflict must be 'Abort' or 'Overwrite' for paginated reports"
            )

        dataset_display_name = display_name.strip()
        if not dataset_display_name:
            raise ValueError("display_name must be non-empty")
        if not dataset_display_name.lower().endswith(".rdl"):
            dataset_display_name = f"{dataset_display_name}.rdl"

        params = {
            "datasetDisplayName": dataset_display_name,
            "nameConflict": name_conflict,
        }
        files = {
            "file": (
                dataset_display_name,
                rdl_bytes,
                "application/octet-stream",
            ),
        }
        response = self._client.post(
            f"{self.base_url}/groups/{group_id}/imports",
            headers=self._auth_headers(),
            params=params,
            files=files,
        )
        if response.status_code not in (200, 202):
            self._raise_api_error(response)

        payload = self._json_or_none(response)
        if not isinstance(payload, dict) or not payload.get("id"):
            raise PowerBiApiError(
                "Import response missing import id",
                status_code=response.status_code,
                details=payload,
            )

        if not wait:
            return payload

        return self.wait_for_import(group_id, str(payload["id"]))

    def import_pbix(
        self,
        group_id: str,
        pbix_bytes: bytes,
        *,
        dataset_display_name: str,
        name_conflict: str = "Abort",
        skip_report: bool = False,
        wait: bool = True,
    ) -> dict[str, Any]:
        """Import a ``.pbix`` via POST /groups/{groupId}/imports; optionally wait.

        When *skip_report* is True, only the semantic model is imported (must be
        True if set — Power BI API requirement).
        """
        allowed = {
            "Abort",
            "CreateOrOverwrite",
            "GenerateUniqueName",
            "Ignore",
            "Overwrite",
        }
        if name_conflict not in allowed:
            raise ValueError(
                "name_conflict must be one of: " + ", ".join(sorted(allowed))
            )

        params: dict[str, str] = {
            "datasetDisplayName": dataset_display_name,
            "nameConflict": name_conflict,
        }
        if skip_report:
            params["skipReport"] = "true"

        filename = dataset_display_name
        if not filename.lower().endswith(".pbix"):
            filename = f"{filename}.pbix"
        files = {
            "file": (filename, pbix_bytes, "application/octet-stream"),
        }
        response = self._client.post(
            f"{self.base_url}/groups/{group_id}/imports",
            headers=self._auth_headers(),
            params=params,
            files=files,
        )
        if response.status_code not in (200, 202):
            self._raise_api_error(response)

        payload = self._json_or_none(response)
        if not isinstance(payload, dict) or not payload.get("id"):
            raise PowerBiApiError(
                "Import response missing import id",
                status_code=response.status_code,
                details=payload,
            )

        if not wait:
            return payload

        return self.wait_for_import(group_id, str(payload["id"]))

    def get_dataflow(self, group_id: str, dataflow_id: str) -> dict[str, Any]:
        """Resolve a dataflow by id from the workspace list (name/metadata)."""
        for item in self.list_dataflows(group_id):
            object_id = item.get("objectId") or item.get("id")
            if object_id == dataflow_id:
                return item
        raise PowerBiApiError(
            f"Dataflow {dataflow_id} not found in group {group_id}",
            status_code=404,
            error_code="DataflowNotFound",
        )

    def get_dataflow_definition(
        self, group_id: str, dataflow_id: str
    ) -> dict[str, Any]:
        """GET /groups/{groupId}/dataflows/{dataflowId} — export model.json."""
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}/dataflows/{dataflow_id}",
            headers=self._json_headers(),
        )
        if response.status_code != 200:
            self._raise_api_error(response)
        result = self._json_or_none(response)
        if not isinstance(result, dict):
            raise PowerBiApiError("Unexpected empty dataflow definition response")
        return result

    def delete_dataflow(self, group_id: str, dataflow_id: str) -> None:
        """DELETE /groups/{groupId}/dataflows/{dataflowId}."""
        response = self._client.delete(
            f"{self.base_url}/groups/{group_id}/dataflows/{dataflow_id}",
            headers=self._json_headers(),
        )
        if response.status_code not in (200, 204):
            self._raise_api_error(response)

    def create_dataflow_from_model(
        self,
        group_id: str,
        model_json_bytes: bytes,
        *,
        name_conflict: str = "Abort",
        wait: bool = True,
    ) -> dict[str, Any]:
        """Import a Gen1 dataflow from model.json bytes; optionally wait for completion.

        Returns the completed Import object. Use :func:`dataflow_id_from_import` to
        extract the created dataflow id.
        """
        if name_conflict not in {"Abort", "GenerateUniqueName"}:
            raise ValueError(
                "name_conflict must be 'Abort' or 'GenerateUniqueName' for dataflows"
            )

        params = {
            "datasetDisplayName": "model.json",
            "nameConflict": name_conflict,
        }
        files = {
            "model.json": ("model.json", model_json_bytes, "application/json"),
        }
        response = self._client.post(
            f"{self.base_url}/groups/{group_id}/imports",
            headers=self._auth_headers(),
            params=params,
            files=files,
        )
        if response.status_code not in (200, 202):
            self._raise_api_error(response)

        payload = self._json_or_none(response)
        if not isinstance(payload, dict) or not payload.get("id"):
            raise PowerBiApiError(
                "Import response missing import id",
                status_code=response.status_code,
                details=payload,
            )

        if not wait:
            return payload

        return self.wait_for_import(group_id, str(payload["id"]))

    def wait_for_import(self, group_id: str, import_id: str) -> dict[str, Any]:
        """Poll GET /groups/{groupId}/imports/{importId} until terminal state."""
        retry_after = DEFAULT_RETRY_AFTER_SECONDS

        while True:
            self._sleep(retry_after)
            response = self._client.get(
                f"{self.base_url}/groups/{group_id}/imports/{import_id}",
                headers=self._json_headers(),
            )
            if response.status_code != 200:
                self._raise_api_error(response)

            payload = self._json_or_none(response)
            if not isinstance(payload, dict):
                raise PowerBiApiError("Unexpected empty import status response")

            state = payload.get("importState")
            if state == "Succeeded":
                return payload
            if state == "Failed":
                error = payload.get("error")
                message = "Power BI import failed"
                error_code = None
                if isinstance(error, dict):
                    error_code = error.get("code")
                    details = error.get("details")
                    if isinstance(details, list) and details:
                        first = details[0]
                        if isinstance(first, dict) and first.get("message"):
                            message = str(first["message"])
                    elif error_code:
                        message = f"Power BI import failed ({error_code})"
                raise PowerBiApiError(
                    message,
                    status_code=response.status_code,
                    error_code=error_code,
                    details=error or payload,
                )
            if (
                state not in (None, "Publishing")
                and state not in IMPORT_TERMINAL_STATES
            ):
                # Unknown non-terminal state — keep polling briefly.
                pass

    def refresh_dataset(
        self,
        group_id: str,
        dataset_id: str,
        *,
        notify_option: str = "NoNotification",
    ) -> DatasetRefreshStart:
        """POST /groups/{groupId}/datasets/{datasetId}/refreshes (no wait).

        Standard (non-enhanced) refresh. ``NoNotification`` is the only notify
        option a service principal may use.
        """
        response = self._client.post(
            f"{self.base_url}/groups/{group_id}/datasets/{dataset_id}/refreshes",
            headers=self._json_headers(),
            json={"notifyOption": notify_option},
        )
        if response.status_code not in (200, 202):
            self._raise_api_error(response)
        location = response.headers.get("Location") or None
        return DatasetRefreshStart(
            group_id=group_id,
            dataset_id=dataset_id,
            request_id=response.headers.get("x-ms-request-id") or None,
            refresh_id=_refresh_id_from_location(location),
            location=location,
        )

    def list_dataset_refreshes(
        self, group_id: str, dataset_id: str, *, top: int = 10
    ) -> list[dict[str, Any]]:
        """GET /groups/{groupId}/datasets/{datasetId}/refreshes (newest first)."""
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}/datasets/{dataset_id}/refreshes",
            headers=self._json_headers(),
            params={"$top": str(top)},
        )
        if response.status_code != 200:
            self._raise_api_error(response)
        result = self._json_or_none(response)
        if not isinstance(result, dict):
            raise PowerBiApiError("Unexpected empty refresh history response")
        value = result.get("value")
        if not isinstance(value, list):
            raise PowerBiApiError("Refresh history response missing 'value'")
        return [entry for entry in value if isinstance(entry, dict)]

    def wait_for_dataset_refresh(
        self,
        refresh: DatasetRefreshStart,
        *,
        poll_seconds: int = REFRESH_POLL_SECONDS,
        on_poll: Callable[[dict[str, Any] | None], None] | None = None,
    ) -> dict[str, Any]:
        """Poll refresh history until the started refresh completes; raise on failure.

        Matches the history entry by ``requestId`` (the refresh id from
        ``Location`` or the ``x-ms-request-id`` header). *on_poll* receives the
        in-progress entry, or ``None`` before it appears in history.
        """
        wanted = {rid for rid in (refresh.refresh_id, refresh.request_id) if rid}
        if not wanted:
            raise PowerBiApiError(
                "Refresh response missing request id; cannot poll refresh status"
            )
        while True:
            self._sleep(poll_seconds)
            entries = self.list_dataset_refreshes(refresh.group_id, refresh.dataset_id)
            entry = next(
                (e for e in entries if str(e.get("requestId") or "") in wanted),
                None,
            )
            status = entry.get("status") if entry else None
            if status == "Completed":
                return entry
            if entry is not None and status in REFRESH_FAILED_STATUSES:
                raise _refresh_failure_error(entry, str(status))
            if on_poll is not None:
                on_poll(entry)

    def get_import(self, group_id: str, import_id: str) -> dict[str, Any]:
        """GET /groups/{groupId}/imports/{importId}."""
        response = self._client.get(
            f"{self.base_url}/groups/{group_id}/imports/{import_id}",
            headers=self._json_headers(),
        )
        if response.status_code != 200:
            self._raise_api_error(response)
        result = self._json_or_none(response)
        if not isinstance(result, dict):
            raise PowerBiApiError("Unexpected empty import response")
        return result

    @staticmethod
    def _json_or_none(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise PowerBiApiError(
                "Response was not valid JSON",
                status_code=response.status_code,
                details=response.text,
            ) from exc

    @staticmethod
    def _raise_api_error(response: httpx.Response) -> None:
        error_code = None
        message = f"Power BI API request failed with HTTP {response.status_code}"
        request_id = None
        details: Any = None
        try:
            details = response.json()
        except ValueError:
            details = response.text or None
        if isinstance(details, dict):
            error = details.get("error")
            if isinstance(error, dict):
                message = error.get("message") or message
                error_code = error.get("code") or error.get("errorCode")
            else:
                message = details.get("message") or message
                error_code = details.get("errorCode") or details.get("code")
            request_id = details.get("requestId")
        raise PowerBiApiError(
            message,
            status_code=response.status_code,
            error_code=error_code,
            request_id=request_id,
            details=details,
        )


def _refresh_id_from_location(location: str | None) -> str | None:
    """Last path segment after ``/refreshes/`` (``None`` when absent)."""
    if not location:
        return None
    segments = [part for part in urlparse(location).path.split("/") if part]
    if len(segments) >= 2 and segments[-2].lower() == "refreshes":
        return segments[-1]
    return None


def _refresh_failure_error(entry: dict[str, Any], status: str) -> PowerBiApiError:
    message = f"Semantic model refresh {status.lower()}"
    error_code = None
    raw = entry.get("serviceExceptionJson")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            error_code = parsed.get("errorCode")
            description = parsed.get("errorDescription")
            if isinstance(description, str) and description.strip():
                message = description.strip()
            elif error_code:
                message = f"{message} ({error_code})"
    return PowerBiApiError(
        message,
        error_code=error_code,
        request_id=entry.get("requestId"),
        details=entry,
    )


def dataflow_id_from_import(import_payload: dict[str, Any]) -> str | None:
    """Extract the created dataflow object id from a completed Import payload."""
    dataflows = import_payload.get("dataflows")
    if isinstance(dataflows, list):
        for item in dataflows:
            if not isinstance(item, dict):
                continue
            object_id = (
                item.get("objectId") or item.get("id") or item.get("targetDataflowId")
            )
            if object_id:
                return str(object_id)
    return None


def report_id_from_import(import_payload: dict[str, Any]) -> str | None:
    """Extract the created/updated report id from a completed Import payload."""
    report_id, _ = report_and_dataset_ids_from_import(import_payload)
    return report_id


def report_and_dataset_ids_from_import(
    import_payload: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Extract ``(report_id, dataset_id)`` from a completed Import payload."""
    report_id: str | None = None
    dataset_id: str | None = None
    reports = import_payload.get("reports")
    if isinstance(reports, list):
        for item in reports:
            if isinstance(item, dict) and item.get("id"):
                report_id = str(item["id"])
                break
    datasets = import_payload.get("datasets")
    if isinstance(datasets, list):
        for item in datasets:
            if isinstance(item, dict) and item.get("id"):
                dataset_id = str(item["id"])
                break
    return report_id, dataset_id
