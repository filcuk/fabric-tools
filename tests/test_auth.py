"""Tests for auth helpers (persistence paths and credential wiring)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AuthenticationRecord, ChainedTokenCredential

from fabric_tools import auth


def test_auth_record_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    record = AuthenticationRecord(
        authority="login.microsoftonline.com",
        client_id="00000000-0000-0000-0000-000000000001",
        home_account_id="user.tenant",
        tenant_id="00000000-0000-0000-0000-000000000002",
        username="user@example.com",
    )
    auth.save_authentication_record(record)
    loaded = auth.load_authentication_record()
    assert loaded is not None
    assert loaded.username == "user@example.com"
    assert loaded.tenant_id == record.tenant_id
    assert (
        auth.auth_record_path() == tmp_path / "fabric-tools" / "msal-auth-record.json"
    )


def test_load_authentication_record_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert auth.load_authentication_record() is None


def test_load_authentication_record_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = auth.auth_record_path()
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")
    assert auth.load_authentication_record() is None


def test_persisting_credential_saves_record_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    inner = MagicMock()
    inner.get_token.return_value = AccessToken("tok", 9999999999)
    record = AuthenticationRecord(
        authority="login.microsoftonline.com",
        client_id="cid",
        home_account_id="hid",
        tenant_id="tid",
        username="u@example.com",
    )
    inner.authenticate.return_value = record

    wrapped = auth._PersistingAuthRecordCredential(inner)
    assert wrapped.get_token("scope").token == "tok"
    assert wrapped.get_token("scope").token == "tok"
    assert inner.authenticate.call_count == 1
    loaded = auth.load_authentication_record()
    assert loaded is not None
    assert loaded.username == "u@example.com"


def test_token_provider_uses_requested_scope() -> None:
    cred = MagicMock()
    cred.get_token.return_value = AccessToken("pbi-tok", 9999999999)
    provide = auth.token_provider(cred, scope=auth.POWER_BI_SCOPE)
    assert provide() == "pbi-tok"
    cred.get_token.assert_called_once_with(auth.POWER_BI_SCOPE)


def test_token_provider_defaults_to_fabric_scope() -> None:
    cred = MagicMock()
    cred.get_token.return_value = AccessToken("fab-tok", 9999999999)
    provide = auth.token_provider(cred)
    assert provide() == "fab-tok"
    cred.get_token.assert_called_once_with(auth.FABRIC_SCOPE)


def test_create_credential_chain_includes_environment(monkeypatch) -> None:
    monkeypatch.setattr(auth, "load_authentication_record", lambda: None)
    monkeypatch.setattr(auth, "_broker_credential", lambda *, interactive=True: None)
    cred = auth.create_credential()
    assert isinstance(cred, ChainedTokenCredential)


def test_broker_credential_when_available(monkeypatch) -> None:
    monkeypatch.setattr(auth.os, "name", "nt")
    monkeypatch.setattr(auth, "load_authentication_record", lambda: None)
    mock_cred = MagicMock()
    mock_cls = MagicMock(return_value=mock_cred)
    with patch(
        "azure.identity.broker.InteractiveBrowserBrokerCredential",
        mock_cls,
    ):
        result = auth._broker_credential()
    assert isinstance(result, auth._PersistingAuthRecordCredential)
    mock_cls.assert_called_once()
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["use_default_broker_account"] is True
    assert "disable_automatic_authentication" not in kwargs
    assert "cache_persistence_options" in kwargs
    assert "parent_window_handle" in kwargs


def test_broker_credential_silent_disables_interactive(monkeypatch) -> None:
    monkeypatch.setattr(auth.os, "name", "nt")
    monkeypatch.setattr(auth, "load_authentication_record", lambda: None)
    mock_cls = MagicMock(return_value=MagicMock())
    with patch(
        "azure.identity.broker.InteractiveBrowserBrokerCredential",
        mock_cls,
    ):
        result = auth._broker_credential(interactive=False)
    assert isinstance(result, auth._PersistingAuthRecordCredential)
    assert mock_cls.call_args.kwargs["disable_automatic_authentication"] is True


def test_broker_credential_skipped_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(auth.os, "name", "posix")
    assert auth._broker_credential() is None


def test_timed_credential_returns_token() -> None:
    inner = MagicMock()
    inner.get_token.return_value = AccessToken("tok", 9999999999)
    wrapped = auth._TimedCredential(inner, timeout=1.0, label="test")
    assert wrapped.get_token("scope").token == "tok"


def test_timed_credential_propagates_error() -> None:
    from azure.identity import CredentialUnavailableError

    inner = MagicMock()
    inner.get_token.side_effect = CredentialUnavailableError(message="nope")
    wrapped = auth._TimedCredential(inner, timeout=1.0, label="test")
    with pytest.raises(CredentialUnavailableError, match="nope"):
        wrapped.get_token("scope")


def test_timed_credential_times_out() -> None:
    from azure.identity import CredentialUnavailableError

    inner = MagicMock()

    def hang(*_args, **_kwargs):
        time.sleep(5)

    inner.get_token.side_effect = hang
    wrapped = auth._TimedCredential(inner, timeout=0.05, label="Windows sign-in prompt")
    with pytest.raises(
        CredentialUnavailableError, match="trying another sign-in method"
    ):
        wrapped.get_token("scope")


def test_chain_continue_converts_hard_failures() -> None:
    from azure.identity import CredentialUnavailableError

    inner = MagicMock()
    inner.get_token.side_effect = ClientAuthenticationError(
        "User canceled the flow. Status: Response_Status.Status_UserCanceled"
    )
    wrapped = auth._ChainContinueCredential(inner)
    with pytest.raises(CredentialUnavailableError, match="User canceled"):
        wrapped.get_token("scope")


def test_chain_continue_passes_unavailable() -> None:
    from azure.identity import CredentialUnavailableError

    inner = MagicMock()
    inner.get_token.side_effect = CredentialUnavailableError(message="missing env")
    wrapped = auth._ChainContinueCredential(inner)
    with pytest.raises(CredentialUnavailableError, match="missing env"):
        wrapped.get_token("scope")


def test_auth_error_from_user_cancel() -> None:
    err = auth.auth_error_from_exception(
        ClientAuthenticationError(
            "ChainedTokenCredential failed...\n"
            "_PersistingAuthRecordCredential: User canceled the flow. "
            "Status: Response_Status.Status_UserCanceled"
        )
    )
    assert err.canceled is True
    assert str(err) == "Sign-in was canceled."


def test_auth_error_from_generic_failure() -> None:
    err = auth.auth_error_from_exception(
        ClientAuthenticationError("ChainedTokenCredential failed to retrieve a token")
    )
    assert err.canceled is False
    assert "Authentication failed" in str(err)


def test_get_access_token_raises_auth_error() -> None:
    cred = MagicMock()
    cred.get_token.side_effect = ClientAuthenticationError(
        "User canceled the flow. Status_UserCanceled"
    )
    with pytest.raises(auth.AuthError, match="Sign-in was canceled"):
        auth.get_access_token(cred)


def test_broker_interactive_unreliable_in_vscode(monkeypatch) -> None:
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    monkeypatch.delenv("VSCODE_INJECTION", raising=False)
    monkeypatch.setattr(auth, "_stderr_is_tty", lambda: True)
    assert auth._broker_interactive_unreliable() is True


def test_broker_interactive_unreliable_non_tty(monkeypatch) -> None:
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.delenv("VSCODE_INJECTION", raising=False)
    monkeypatch.setattr(auth, "_stderr_is_tty", lambda: False)
    assert auth._broker_interactive_unreliable() is True


def test_broker_interactive_ok_on_console(monkeypatch) -> None:
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.delenv("VSCODE_INJECTION", raising=False)
    monkeypatch.setattr(auth, "_stderr_is_tty", lambda: True)
    assert auth._broker_interactive_unreliable() is False


def test_create_credential_skips_interactive_broker_in_ide(monkeypatch) -> None:
    monkeypatch.setattr(auth, "load_authentication_record", lambda: None)
    monkeypatch.setattr(auth, "_broker_interactive_unreliable", lambda: True)
    silent = MagicMock()
    monkeypatch.setattr(
        auth,
        "_broker_credential",
        lambda *, interactive=True: silent if not interactive else MagicMock(),
    )
    cred = auth.create_credential()
    assert isinstance(cred, ChainedTokenCredential)
    timed = []
    for c in cred.credentials:
        if not isinstance(c, auth._AnnouncingCredential):
            continue
        inner = c._inner
        if isinstance(inner, auth._ChainContinueCredential):
            inner = inner._inner
        if isinstance(inner, auth._TimedCredential):
            timed.append(inner)
    assert len(timed) == 1
    assert timed[0]._timeout == auth._SILENT_BROKER_TIMEOUT_SECONDS


def test_create_credential_includes_timed_interactive_broker(monkeypatch) -> None:
    monkeypatch.setattr(auth, "load_authentication_record", lambda: None)
    monkeypatch.setattr(auth, "_broker_interactive_unreliable", lambda: False)
    monkeypatch.setattr(
        auth,
        "_broker_credential",
        lambda *, interactive=True: MagicMock(),
    )
    cred = auth.create_credential()
    timeouts = []
    for c in cred.credentials:
        if not isinstance(c, auth._AnnouncingCredential):
            continue
        inner = c._inner
        if isinstance(inner, auth._ChainContinueCredential):
            inner = inner._inner
        if isinstance(inner, auth._TimedCredential):
            timeouts.append(inner._timeout)
    assert timeouts == [
        auth._SILENT_BROKER_TIMEOUT_SECONDS,
        auth._INTERACTIVE_BROKER_TIMEOUT_SECONDS,
    ]


def test_announcing_credential_updates_status(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(auth, "_announce", messages.append)
    inner = MagicMock()
    inner.get_token.return_value = AccessToken("tok", 9999999999)
    msg = auth.status_detail("auth", "authenticating", "browser")
    wrapped = auth._AnnouncingCredential(inner, msg)
    assert wrapped.get_token("scope").token == "tok"
    assert wrapped.get_token("scope").token == "tok"
    assert messages == [msg]


def test_announce_does_not_overwrite_non_auth_status(monkeypatch) -> None:
    updates: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: updates.append(msg),
    )
    monkeypatch.setattr(
        "fabric_tools.status.current_message",
        lambda: "1 of 2 · report: comparing (aaaaaaaa…)…",
    )
    auth._announce(auth.status_detail("auth", "authenticating", "Windows account"))
    assert updates == []


def test_announce_updates_when_status_is_authenticating(monkeypatch) -> None:
    updates: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.status.update",
        lambda msg: updates.append(msg),
    )
    monkeypatch.setattr(
        "fabric_tools.status.current_message",
        lambda: auth.AUTH_STATUS_PREFIX + "…",
    )
    msg = auth.status_detail("auth", "authenticating", "Windows account")
    auth._announce(msg)
    assert updates == [msg]


def test_device_code_prompt_announces_code(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(auth, "_announce", messages.append)
    auth._device_code_prompt("https://microsoft.com/devicelogin", "ABCD1234", None)
    assert "ABCD1234" in messages[0]
    assert "https://microsoft.com/devicelogin" in messages[0]
