"""Azure AD authentication for the Fabric REST API."""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fabric_tools.status import AUTH_STATUS_PREFIX, status_detail

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

_AZURE_IDENTITY_LOG = logging.getLogger("azure.identity")
_CANCEL_MARKERS = (
    "user canceled",
    "user cancelled",
    "usercanceled",
    "status_usercanceled",
    "authentication_canceled",
    "auth_canceled",
)


class AuthError(RuntimeError):
    """User-facing authentication failure (short message for the CLI)."""

    def __init__(self, message: str, *, canceled: bool = False) -> None:
        super().__init__(message)
        self.canceled = canceled


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
    from fabric_tools.status import current_message, update

    # Do not overwrite download/deploy/compare progress during later token refreshes.
    active = current_message()
    if active is not None and not active.startswith(AUTH_STATUS_PREFIX):
        return
    update(message)


def _close_inner(inner: object) -> None:
    close = getattr(inner, "close", None)
    if close is not None:
        close()


def _quiet_azure_identity_logging() -> None:
    """Avoid dumping long ChainedTokenCredential histories to stderr."""
    _AZURE_IDENTITY_LOG.setLevel(logging.CRITICAL)


def _short_error_text(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    first = text.splitlines()[0].strip()
    if len(first) > 200:
        return first[:197] + "..."
    return first


def _looks_canceled(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CANCEL_MARKERS)


def auth_error_from_exception(exc: BaseException) -> AuthError:
    """Map an Azure Identity failure to a short CLI message."""
    text = str(exc)
    if _looks_canceled(text):
        return AuthError("Sign-in was canceled.", canceled=True)
    return AuthError(
        "Authentication failed. Complete sign-in when prompted, or set "
        "AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET."
    )


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
    """Update the CLI status line before the first ``get_token`` attempt."""

    def __init__(self, inner: TokenCredential, message: str) -> None:
        self._inner = inner
        self._message = message
        self._announced = False

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        if not self._announced:
            _announce(self._message)
            self._announced = True
        return self._inner.get_token(*scopes, **kwargs)

    def close(self) -> None:
        _close_inner(self._inner)


class _ChainContinueCredential:
    """Turn hard auth failures into ``CredentialUnavailableError`` so the chain continues.

    ``ChainedTokenCredential`` stops on any non-unavailable exception (e.g. user cancel),
    which would skip browser / device-code fallbacks.
    """

    def __init__(self, inner: TokenCredential) -> None:
        self._inner = inner

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        from azure.identity import CredentialUnavailableError

        try:
            return self._inner.get_token(*scopes, **kwargs)
        except CredentialUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - must not break the credential chain
            raise CredentialUnavailableError(message=_short_error_text(exc)) from exc

    def close(self) -> None:
        _close_inner(self._inner)


class _TimedCredential:
    """Fail a hanging ``get_token`` so ``ChainedTokenCredential`` can try the next."""

    def __init__(self, inner: TokenCredential, *, timeout: float, label: str) -> None:
        self._inner = inner
        self._timeout = timeout
        self._label = label

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        from azure.identity import CredentialUnavailableError

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
            raise CredentialUnavailableError(
                message=(
                    f"{self._label} did not complete within {seconds} seconds; "
                    "trying another sign-in method."
                )
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
        f"{status_detail('auth', 'authenticating', 'device code')} open {verification_uri} and enter {user_code}"
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

    Hard failures (including user cancel) are converted so the chain continues to the
    next method instead of aborting early.
    """
    from azure.identity import (
        ChainedTokenCredential,
        DeviceCodeCredential,
        EnvironmentCredential,
        InteractiveBrowserCredential,
    )

    _quiet_azure_identity_logging()

    credentials: list[TokenCredential] = [EnvironmentCredential()]

    silent_broker = _broker_credential(interactive=False)
    if silent_broker is not None:
        credentials.append(
            _AnnouncingCredential(
                _ChainContinueCredential(
                    _TimedCredential(
                        silent_broker,
                        timeout=_SILENT_BROKER_TIMEOUT_SECONDS,
                        label="Windows account sign-in",
                    )
                ),
                status_detail("auth", "authenticating", "Windows account"),
            )
        )

    if not _broker_interactive_unreliable():
        interactive_broker = _broker_credential(interactive=True)
        if interactive_broker is not None:
            credentials.append(
                _AnnouncingCredential(
                    _ChainContinueCredential(
                        _TimedCredential(
                            interactive_broker,
                            timeout=_INTERACTIVE_BROKER_TIMEOUT_SECONDS,
                            label="Windows sign-in prompt",
                        )
                    ),
                    f"{status_detail('auth', 'authenticating', 'Windows')} check the taskbar or another "
                    "monitor if no dialog appears",
                )
            )

    user_kwargs = _user_credential_kwargs()
    credentials.append(
        _AnnouncingCredential(
            _ChainContinueCredential(
                _PersistingAuthRecordCredential(
                    InteractiveBrowserCredential(**user_kwargs)
                )
            ),
            f"{status_detail('auth', 'authenticating', 'browser')} a sign-in window should open",
        )
    )
    credentials.append(
        _AnnouncingCredential(
            _ChainContinueCredential(
                _PersistingAuthRecordCredential(
                    DeviceCodeCredential(
                        **user_kwargs,
                        prompt_callback=_device_code_prompt,
                    )
                )
            ),
            status_detail("auth", "authenticating", "device code"),
        )
    )
    return ChainedTokenCredential(*credentials)


def get_access_token(
    credential: TokenCredential | None = None,
    *,
    scope: str = FABRIC_SCOPE,
) -> AccessToken:
    """Acquire an access token for the given API scope (Fabric by default)."""
    from azure.core.exceptions import ClientAuthenticationError

    _quiet_azure_identity_logging()
    cred = credential or create_credential()
    try:
        return cred.get_token(scope)
    except ClientAuthenticationError as exc:
        raise auth_error_from_exception(exc) from None


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
