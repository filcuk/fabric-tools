"""Azure AD authentication for the Fabric REST API."""

from __future__ import annotations

import os
import sys
import threading
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
# Silent WAM / cached-account reuse should finish quickly or give up.
_SILENT_BROKER_TIMEOUT_SECONDS = 10.0
# Interactive WAM can hang forever in IDE terminals; cap it so later methods run.
_INTERACTIVE_BROKER_TIMEOUT_SECONDS = 45.0

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


def _stderr_is_tty() -> bool:
    try:
        return bool(sys.stderr.isatty())
    except OSError:
        return False


def _broker_interactive_unreliable() -> bool:
    """True when a WAM account picker is unlikely to appear (IDE / non-TTY)."""
    if os.environ.get("TERM_PROGRAM", "").lower() == "vscode":
        return True
    if os.environ.get("VSCODE_INJECTION"):
        return True
    return not _stderr_is_tty()


def _announce(message: str) -> None:
    from fabric_tools.status import update

    update(message)


def _close_inner(inner: object) -> None:
    close = getattr(inner, "close", None)
    if close is not None:
        close()


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
        _close_inner(self._inner)


class _AnnouncingCredential:
    """Update the CLI status line before delegating ``get_token``."""

    def __init__(self, inner: TokenCredential, message: str) -> None:
        self._inner = inner
        self._message = message

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        _announce(self._message)
        return self._inner.get_token(*scopes, **kwargs)

    def close(self) -> None:
        _close_inner(self._inner)


class _TimedCredential:
    """Fail a hanging ``get_token`` so ``ChainedTokenCredential`` can try the next."""

    def __init__(self, inner: TokenCredential, *, timeout: float, label: str) -> None:
        self._inner = inner
        self._timeout = timeout
        self._label = label

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        from azure.core.exceptions import ClientAuthenticationError

        holder: dict[str, Any] = {}

        def run() -> None:
            try:
                holder["token"] = self._inner.get_token(*scopes, **kwargs)
            except Exception as exc:  # noqa: BLE001 - re-raised on the caller thread
                holder["error"] = exc

        thread = threading.Thread(
            target=run,
            name="fabric-tools-auth",
            daemon=True,
        )
        thread.start()
        thread.join(self._timeout)
        if thread.is_alive():
            seconds = int(self._timeout)
            raise ClientAuthenticationError(
                f"{self._label} did not complete within {seconds} seconds; "
                "trying another sign-in method."
            )
        error = holder.get("error")
        if error is not None:
            raise error
        return holder["token"]

    def close(self) -> None:
        _close_inner(self._inner)


def _device_code_prompt(
    verification_uri: str, user_code: str, expires_on: object
) -> None:
    del expires_on
    _announce(
        f"Authenticating (device code)... open {verification_uri} and enter {user_code}"
    )


def _broker_credential(*, interactive: bool = True) -> TokenCredential | None:
    """Windows WAM (and other OS brokers) when ``azure-identity-broker`` is available."""
    if os.name != "nt":
        return None
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
    if not interactive:
        kwargs["disable_automatic_authentication"] = True
    return _PersistingAuthRecordCredential(InteractiveBrowserBrokerCredential(**kwargs))


def create_credential() -> TokenCredential:
    """Build a credential chain: service principal, WAM broker, browser, device code.

    Service principal uses the standard Azure Identity environment variables:
    ``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``, ``AZURE_CLIENT_SECRET``.

    Interactive credentials use a persistent MSAL token cache and, when available,
    a saved ``AuthenticationRecord`` so later CLI runs can acquire tokens silently.
    On Windows, Web Account Manager (WAM) is tried silently first so the signed-in
    work account (same broker Teams/Office use) can be reused. An interactive WAM
    prompt is skipped in IDE / non-TTY sessions (where it often never appears) and
    otherwise time-capped so browser and device-code auth can run.
    """
    from azure.identity import (
        ChainedTokenCredential,
        DeviceCodeCredential,
        EnvironmentCredential,
        InteractiveBrowserCredential,
    )

    credentials: list[TokenCredential] = [EnvironmentCredential()]

    silent_broker = _broker_credential(interactive=False)
    if silent_broker is not None:
        credentials.append(
            _AnnouncingCredential(
                _TimedCredential(
                    silent_broker,
                    timeout=_SILENT_BROKER_TIMEOUT_SECONDS,
                    label="Windows account sign-in",
                ),
                "Authenticating (Windows account)...",
            )
        )

    if not _broker_interactive_unreliable():
        interactive_broker = _broker_credential(interactive=True)
        if interactive_broker is not None:
            credentials.append(
                _AnnouncingCredential(
                    _TimedCredential(
                        interactive_broker,
                        timeout=_INTERACTIVE_BROKER_TIMEOUT_SECONDS,
                        label="Windows sign-in prompt",
                    ),
                    "Authenticating (Windows)... check the taskbar or another "
                    "monitor if no dialog appears",
                )
            )

    user_kwargs = _user_credential_kwargs()
    credentials.append(
        _AnnouncingCredential(
            _PersistingAuthRecordCredential(
                InteractiveBrowserCredential(**user_kwargs)
            ),
            "Authenticating (browser)... a sign-in window should open",
        )
    )
    credentials.append(
        _AnnouncingCredential(
            _PersistingAuthRecordCredential(
                DeviceCodeCredential(
                    **user_kwargs,
                    prompt_callback=_device_code_prompt,
                )
            ),
            "Authenticating (device code)...",
        )
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
