"""Azure AD authentication for the Fabric REST API."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from azure.core.credentials import AccessToken, TokenCredential
    from azure.identity import AuthenticationRecord, TokenCachePersistenceOptions

FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
POWER_BI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_CACHE_NAME = "fabric-tools"
_AUTH_RECORD_FILENAME = "msal-auth-record.json"

TokenProvider = Callable[[], str]


def _auth_data_dir() -> Path:
    """Directory for persisted auth state (tokens live in the MSAL cache separately)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "fabric-tools"
        return Path.home() / "AppData" / "Local" / "fabric-tools"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "fabric-tools"
    return Path.home() / ".config" / "fabric-tools"


def auth_record_path() -> Path:
    """Path to the serialized ``AuthenticationRecord`` used for silent re-auth."""
    return _auth_data_dir() / _AUTH_RECORD_FILENAME


def load_authentication_record() -> AuthenticationRecord | None:
    """Load a previously saved authentication record, or ``None`` if missing/invalid."""
    from azure.identity import AuthenticationRecord

    path = auth_record_path()
    try:
        data = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return AuthenticationRecord.deserialize(data)
    except (TypeError, ValueError, KeyError):
        return None


def save_authentication_record(record: AuthenticationRecord) -> None:
    """Persist an authentication record for later silent token acquisition."""
    path = auth_record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.serialize(), encoding="utf-8")


def _cache_persistence_options() -> TokenCachePersistenceOptions:
    from azure.identity import TokenCachePersistenceOptions

    return TokenCachePersistenceOptions(name=_CACHE_NAME)


def _user_credential_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "additionally_allowed_tenants": ["*"],
        "cache_persistence_options": _cache_persistence_options(),
    }
    record = load_authentication_record()
    if record is not None:
        kwargs["authentication_record"] = record
    return kwargs


class _PersistingAuthRecordCredential:
    """Wrap a credential and save ``AuthenticationRecord`` after a successful token."""

    def __init__(self, inner: TokenCredential) -> None:
        self._inner = inner
        self._record_saved = False

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        token = self._inner.get_token(*scopes, **kwargs)
        if self._record_saved:
            return token
        authenticate = getattr(self._inner, "authenticate", None)
        if authenticate is not None:
            try:
                record = authenticate(scopes=scopes)
                save_authentication_record(record)
                self._record_saved = True
            except Exception:  # noqa: BLE001 - persistence must not break API calls
                pass
        return token

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is not None:
            close()


def _broker_credential() -> TokenCredential | None:
    """Windows WAM (and other OS brokers) when ``azure-identity-broker`` is available."""
    try:
        from azure.identity.broker import InteractiveBrowserBrokerCredential
    except ImportError:
        return None

    try:
        import msal
    except ImportError:
        return None

    kwargs = _user_credential_kwargs()
    kwargs["parent_window_handle"] = msal.PublicClientApplication.CONSOLE_WINDOW_HANDLE
    kwargs["use_default_broker_account"] = True
    return _PersistingAuthRecordCredential(InteractiveBrowserBrokerCredential(**kwargs))


def create_credential() -> TokenCredential:
    """Build a credential chain: service principal, WAM broker, browser, device code.

    Service principal uses the standard Azure Identity environment variables:
    ``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``, ``AZURE_CLIENT_SECRET``.

    Interactive credentials use a persistent MSAL token cache and, when available,
    a saved ``AuthenticationRecord`` so later CLI runs can acquire tokens silently.
    On Windows, Web Account Manager (WAM) is tried first so the signed-in work
    account (same broker Teams/Office use) can be reused.
    """
    from azure.identity import (
        ChainedTokenCredential,
        DeviceCodeCredential,
        EnvironmentCredential,
        InteractiveBrowserCredential,
    )

    credentials: list[TokenCredential] = [EnvironmentCredential()]

    broker = _broker_credential()
    if broker is not None:
        credentials.append(broker)

    user_kwargs = _user_credential_kwargs()
    credentials.append(
        _PersistingAuthRecordCredential(InteractiveBrowserCredential(**user_kwargs))
    )
    credentials.append(
        _PersistingAuthRecordCredential(DeviceCodeCredential(**user_kwargs))
    )
    return ChainedTokenCredential(*credentials)


def get_access_token(
    credential: TokenCredential | None = None,
    *,
    scope: str = FABRIC_SCOPE,
) -> AccessToken:
    """Acquire an access token for the given API scope (Fabric by default)."""
    cred = credential or create_credential()
    return cred.get_token(scope)


def token_provider(
    credential: TokenCredential | None = None,
    *,
    scope: str = FABRIC_SCOPE,
) -> TokenProvider:
    """Return a zero-arg callable that yields a fresh bearer token string."""
    cred = credential or create_credential()

    def _provide() -> str:
        return get_access_token(cred, scope=scope).token

    return _provide


def service_principal_configured() -> bool:
    """True when SP environment variables are all present."""
    return all(
        os.getenv(name)
        for name in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")
    )
