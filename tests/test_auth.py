"""Tests for auth helpers (persistence paths and credential wiring)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from azure.core.credentials import AccessToken
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
    monkeypatch.setattr(auth, "_broker_credential", lambda: None)
    cred = auth.create_credential()
    assert isinstance(cred, ChainedTokenCredential)


def test_broker_credential_when_available(monkeypatch) -> None:
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
    assert "cache_persistence_options" in kwargs
    assert "parent_window_handle" in kwargs
