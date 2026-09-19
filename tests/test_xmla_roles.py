"""Unit tests for PowerShell/XMLA role-membership spike helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fabric_tools.xmla_roles import (
    INSTALL_HINT,
    SCRIPT_ENV,
    XmlaRolesError,
    _parse_response,
    ensure_sqlserver_module,
    invoke_xmla_roles,
    resolve_script_path,
    workspace_xmla_connection,
)


def test_workspace_xmla_connection_encodes_spaces() -> None:
    uri = workspace_xmla_connection("My Workspace")
    assert uri == "powerbi://api.powerbi.com/v1.0/myorg/My%20Workspace"


def test_resolve_script_path_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "custom.ps1"
    script.write_text("# test", encoding="utf-8")
    monkeypatch.setenv(SCRIPT_ENV, str(script))
    assert resolve_script_path() == script.resolve()


def test_resolve_script_path_package_sibling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(SCRIPT_ENV, raising=False)
    pkg = tmp_path / "fabric_tools"
    pkg.mkdir()
    script = pkg / "xmla_role_members.ps1"
    script.write_text("# sibling", encoding="utf-8")
    monkeypatch.setattr(
        "fabric_tools.xmla_roles.__file__",
        str(pkg / "xmla_roles.py"),
    )
    assert resolve_script_path() == script.resolve()


def test_resolve_script_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(SCRIPT_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "fabric_tools.xmla_roles.__file__",
        str(tmp_path / "pkg" / "xmla_roles.py"),
    )
    with pytest.raises(XmlaRolesError, match="not found"):
        resolve_script_path()


def test_ensure_sqlserver_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fabric_tools.xmla_roles.sqlserver_module_available", lambda **_k: False
    )
    with pytest.raises(XmlaRolesError, match=INSTALL_HINT):
        ensure_sqlserver_module(confirm=lambda *_a, **_k: False)


def test_ensure_sqlserver_silent_no_offer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fabric_tools.xmla_roles.sqlserver_module_available", lambda **_k: False
    )
    with pytest.raises(XmlaRolesError, match="not found"):
        ensure_sqlserver_module(silent=True, offer_install=True)


def test_ensure_sqlserver_installs_when_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "fabric_tools.xmla_roles.sqlserver_module_available",
        lambda **_k: False,
    )

    def fake_install(**_k: object) -> None:
        calls.append("install")

    monkeypatch.setattr(
        "fabric_tools.xmla_roles.install_sqlserver_module", fake_install
    )
    ensure_sqlserver_module(confirm=lambda *_a, **_k: True)
    assert calls == ["install"]


def test_parse_response_ok() -> None:
    payload = {
        "ok": True,
        "changed": False,
        "message": "Listed 1 role(s).",
        "roles": [{"name": "r1", "members": []}],
    }
    result = _parse_response(json.dumps(payload), "", 0)
    assert result.ok is True
    assert result.roles[0]["name"] == "r1"


def test_parse_response_error_raises() -> None:
    payload = {
        "ok": False,
        "changed": False,
        "code": "module_missing",
        "message": "SqlServer missing",
    }
    with pytest.raises(XmlaRolesError, match="SqlServer missing") as exc_info:
        _parse_response(json.dumps(payload), "", 2)
    assert exc_info.value.code == "module_missing"


def test_invoke_passes_token_on_stdin_not_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "xmla_role_members.ps1"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr("fabric_tools.xmla_roles.sys.platform", "win32")
    monkeypatch.setattr(
        "fabric_tools.xmla_roles.ensure_sqlserver_module", lambda **_k: None
    )
    monkeypatch.setattr(
        "fabric_tools.xmla_roles.find_powershell", lambda: "powershell.exe"
    )

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return MagicMock(
            returncode=0,
            stdout=json.dumps(
                {"ok": True, "changed": False, "message": "ok", "roles": []}
            ),
            stderr="",
        )

    monkeypatch.setattr("fabric_tools.xmla_roles.subprocess.run", fake_run)

    secret = "tokensecret-do-not-leak"
    invoke_xmla_roles(
        action="list",
        workspace_name="WS",
        database_name="Model",
        access_token=secret,
        script_path=script,
        offer_install=False,
        silent=True,
    )

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert secret not in cmd
    assert secret not in " ".join(str(c) for c in cmd)
    payload = json.loads(str(captured["input"]))
    assert payload["accessToken"] == secret
    assert payload["action"] == "list"
