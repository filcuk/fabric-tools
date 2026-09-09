"""Power BI REST API client (Dataflow Gen1 and related group APIs)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from fabric_tools.auth import POWER_BI_SCOPE, TokenProvider, token_provider
from fabric_tools.status import update as update_status

DEFAULT_BASE_URL = "https://api.powerbi.com/v1.0/myorg"
DEFAULT_RETRY_AFTER_SECONDS = 2
IMPORT_TERMINAL_STATES = frozenset({"Succeeded", "Failed"})


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


class PowerBiClient:
    """Thin httpx wrapper around Power BI REST APIs used for Dataflow Gen1."""

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

    def get_dataflow_definition(self, group_id: str, dataflow_id: str) -> dict[str, Any]:
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
        update_status(f"Waiting for Power BI import ({import_id})...")
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
            if state not in (None, "Publishing") and state not in IMPORT_TERMINAL_STATES:
                # Unknown non-terminal state — keep polling briefly.
                pass

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


def dataflow_id_from_import(import_payload: dict[str, Any]) -> str | None:
    """Extract the created dataflow object id from a completed Import payload."""
    dataflows = import_payload.get("dataflows")
    if isinstance(dataflows, list):
        for item in dataflows:
            if not isinstance(item, dict):
                continue
            object_id = item.get("objectId") or item.get("id") or item.get(
                "targetDataflowId"
            )
            if object_id:
                return str(object_id)
    return None
