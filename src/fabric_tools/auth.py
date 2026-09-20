"""Azure AD authentication for the Fabric REST API."""

from __future__ import annotations

import os
from collections.abc import Callable

from azure.core.credentials import AccessToken, TokenCredential
from azure.identity import (
    ChainedTokenCredential,
    DeviceCodeCredential,
    EnvironmentCredential,
    InteractiveBrowserCredential,
)

FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

TokenProvider = Callable[[], str]


def create_credential() -> TokenCredential:
    """Build a credential chain: service principal env vars, then interactive.

    Service principal uses the standard Azure Identity environment variables:
    ``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``, ``AZURE_CLIENT_SECRET``.

    When those are unset, interactive browser auth is tried first, then device code.
    """
    return ChainedTokenCredential(
        EnvironmentCredential(),
        InteractiveBrowserCredential(
            additionally_allowed_tenants=["*"],
        ),
        DeviceCodeCredential(
            additionally_allowed_tenants=["*"],
        ),
    )


def get_access_token(
    credential: TokenCredential | None = None,
    *,
    scope: str = FABRIC_SCOPE,
) -> AccessToken:
    """Acquire an access token for the Fabric API."""
    cred = credential or create_credential()
    return cred.get_token(scope)


def token_provider(credential: TokenCredential | None = None) -> TokenProvider:
    """Return a zero-arg callable that yields a fresh bearer token string."""
    cred = credential or create_credential()

    def _provide() -> str:
        return get_access_token(cred).token

    return _provide


def service_principal_configured() -> bool:
    """True when SP environment variables are all present."""
    return all(
        os.getenv(name)
        for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")
    )
