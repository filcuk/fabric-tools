"""Microsoft Fabric REST API client with LRO support."""

from __future__ import annotations

import time
from typing import Any

import httpx

from fabric_tools.auth import TokenProvider, token_provider

DEFAULT_BASE_URL = "https://api.fabric.microsoft.com/v1"
DEFAULT_RETRY_AFTER_SECONDS = 5
TERMINAL_STATUSES = frozenset({"Succeeded", "Failed", "Canceled"})


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

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        """GET /workspaces/{workspaceId}/items/{itemId}."""
        result = self.request("GET", f"/workspaces/{workspace_id}/items/{item_id}")
        if not isinstance(result, dict):
            raise FabricApiError("Unexpected empty item response")
        return result

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
                return self._fetch_operation_result(operation_id, state_response, payload)

            if status in {"Failed", "Canceled"}:
                error = (payload or {}).get("error") if isinstance(payload, dict) else None
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


def _operation_status(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if isinstance(status, str):
        return status
    return None
