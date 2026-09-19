"""Unit tests for PowerShell/XMLA role-membership spike helpers."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fabric_tools.xmla_roles import (
    CONNECT_TIMEOUT_ENV,
    INSTALL_HINT,
    SCRIPT_ENV,
    XmlaRolesError,
    _parse_progress_stage,
    _parse_response,
    ensure_sqlserver_module,
    invoke_xmla_roles,
    resolve_connect_timeout_seconds,
    resolve_script_path,
    stage_action,
    workspace_xmla_connection,
)


def test_workspace_xmla_connection_encodes_spaces() -> None:
    uri = workspace_xmla_connection("Sales Workspace")
    assert uri == "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace"


def test_stage_action_known_and_fallback() -> None:
    assert stage_action("connecting") == "connecting via XMLA"
    assert stage_action("custom_step") == "custom step"


def test_workspace_xmla_connection_personal_v2() -> None:
    uri = workspace_xmla_connection(
        "My workspace",
        workspace_type="Personal",
        tenant_id="11111111-2222-3333-4444-555555555555",
        owner_upn_or_oid="user@contoso.com",
    )
    assert uri == (
        "powerbi://api.powerbi.com/v2.0/11111111-2222-3333-4444-555555555555"
        "/home/myworkspace/user%40contoso.com"
    )


def test_workspace_xmla_connection_personal_requires_owner() -> None:
    with pytest.raises(XmlaRolesError, match="Personal workspace") as exc_info:
        workspace_xmla_connection("My workspace", workspace_type="Personal")
    assert exc_info.value.code == "personal_workspace_xmla"


def test_access_token_claims_and_owner() -> None:
    import base64
    import json

    from fabric_tools.xmla_roles import (
        access_token_claims,
        personal_workspace_owner_from_token,
    )

    payload = {
        "tid": "tenant-guid",
        "upn": "filip@contoso.com",
        "oid": "object-guid",
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    token = f"hdr.{body}.sig"
    assert access_token_claims(token)["tid"] == "tenant-guid"
    assert personal_workspace_owner_from_token(token) == (
        "tenant-guid",
        "object-guid",
    )


def test_is_personal_workspace_by_name() -> None:
    from fabric_tools.xmla_roles import is_personal_workspace

    assert is_personal_workspace(display_name="My workspace") is True
    assert is_personal_workspace(workspace_type="Personal") is True
    assert is_personal_workspace(display_name="Sales") is False


def test_parse_progress_stage() -> None:
    assert _parse_progress_stage("##fabric-tools## stage=connecting") == "connecting"
    assert _parse_progress_stage("noise") is None


def test_resolve_connect_timeout_default() -> None:
    assert resolve_connect_timeout_seconds(overall_timeout=120) == 15


def test_resolve_connect_timeout_capped_by_overall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONNECT_TIMEOUT_ENV, "90")
    assert resolve_connect_timeout_seconds(overall_timeout=30) == 25


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


def test_ensure_workspace_supports_xmla_personal_without_capacity() -> None:
    from fabric_tools.xmla_roles import ensure_workspace_supports_xmla

    with pytest.raises(XmlaRolesError, match="not assigned to a Premium") as exc_info:
        ensure_workspace_supports_xmla(
            {"displayName": "My workspace", "type": "Personal", "capacityId": None}
        )
    assert exc_info.value.code == "xmla_capacity_required"


def test_ensure_workspace_supports_xmla_with_capacity() -> None:
    from fabric_tools.xmla_roles import ensure_workspace_supports_xmla

    ensure_workspace_supports_xmla(
        {
            "displayName": "Sales",
            "type": "Workspace",
            "capacityId": "11111111-2222-3333-4444-555555555555",
        }
    )


def test_ensure_sqlserver_clears_spinner_before_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the install prompt under a live spinner looked like a hang."""
    order: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.xmla_roles.sqlserver_module_available", lambda **_k: False
    )
    monkeypatch.setattr("fabric_tools.status.clear", lambda: order.append("clear"))

    def fake_confirm(*_a: object, **_k: object) -> bool:
        order.append("confirm")
        return False

    with pytest.raises(XmlaRolesError):
        ensure_sqlserver_module(confirm=fake_confirm)
    assert order == ["clear", "confirm"]


def test_invoke_skips_module_check_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "xmla_role_members.ps1"
    script.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr("fabric_tools.xmla_roles.sys.platform", "win32")
    monkeypatch.setattr(
        "fabric_tools.xmla_roles.find_powershell", lambda: "powershell.exe"
    )

    def boom(**_k: object) -> None:
        raise AssertionError("ensure_sqlserver_module must not run")

    monkeypatch.setattr("fabric_tools.xmla_roles.ensure_sqlserver_module", boom)
    monkeypatch.setattr(
        "fabric_tools.xmla_roles._run_xmla_script",
        lambda **_k: MagicMock(
            returncode=0,
            stdout=json.dumps(
                {"ok": True, "changed": False, "message": "ok", "roles": []}
            ),
            stderr="",
        ),
    )
    result = invoke_xmla_roles(
        action="list",
        workspace_name="Sales",
        database_name="Model",
        access_token="tok",
        script_path=script,
        check_module=False,
    )
    assert result.ok is True


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
        "stage": "listing_roles",
    }
    result = _parse_response(json.dumps(payload), "", 0)
    assert result.ok is True
    assert result.roles[0]["name"] == "r1"
    assert result.stage == "listing_roles"


def test_parse_response_error_raises() -> None:
    payload = {
        "ok": False,
        "changed": False,
        "code": "module_missing",
        "message": "SqlServer missing",
        "stage": "starting",
    }
    with pytest.raises(XmlaRolesError, match="SqlServer missing") as exc_info:
        _parse_response(json.dumps(payload), "", 2)
    assert exc_info.value.code == "module_missing"
    assert exc_info.value.stage == "starting"


def test_parse_response_connect_failed_includes_stage() -> None:
    payload = {
        "ok": False,
        "changed": False,
        "code": "connect_failed",
        "message": "XMLA connect failed",
        "stage": "connecting",
    }
    with pytest.raises(XmlaRolesError) as exc_info:
        _parse_response(json.dumps(payload), "", 2)
    assert exc_info.value.code == "connect_failed"
    assert exc_info.value.stage == "connecting"


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

    def fake_run(*, exe, script, payload_json, timeout, on_progress=None):  # type: ignore[no-untyped-def]
        captured["exe"] = exe
        captured["script"] = script
        captured["payload_json"] = payload_json
        captured["timeout"] = timeout
        captured["on_progress"] = on_progress
        return MagicMock(
            returncode=0,
            stdout=json.dumps(
                {"ok": True, "changed": False, "message": "ok", "roles": []}
            ),
            stderr="",
        )

    monkeypatch.setattr("fabric_tools.xmla_roles._run_xmla_script", fake_run)

    secret = "tokensecret-do-not-leak"
    progress_calls: list[str] = []

    def on_progress(stage: str) -> None:
        progress_calls.append(stage)

    invoke_xmla_roles(
        action="list",
        workspace_name="WS",
        database_name="Model",
        access_token=secret,
        script_path=script,
        offer_install=False,
        silent=True,
        on_progress=on_progress,
    )

    assert secret not in str(captured["exe"])
    assert secret not in str(captured["script"])
    payload = json.loads(str(captured["payload_json"]))
    assert payload["accessToken"] == secret
    assert payload["action"] == "list"
    assert payload["connectTimeoutSeconds"] == 15
    assert captured["timeout"] == 20.0
    assert "dataSource" in payload
    assert payload["dataSource"].startswith("powerbi://")
    assert captured["on_progress"] is on_progress


def test_run_xmla_script_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fabric_tools.xmla_roles import _run_xmla_script

    script = tmp_path / "xmla_role_members.ps1"
    script.write_text("# stub", encoding="utf-8")
    kills: list[str] = []

    class FakeProc:
        args = ["powershell.exe"]
        returncode = None
        pid = 4242
        stdin = io.StringIO()
        stdout = io.StringIO("")
        stderr = io.StringIO("##fabric-tools## stage=connecting\n")

        def poll(self) -> int | None:
            return None

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return None

        def kill(self) -> None:
            kills.append("kill")
            self.returncode = 1

    monkeypatch.setattr(
        "fabric_tools.xmla_roles.subprocess.Popen",
        lambda *a, **k: FakeProc(),
    )
    monkeypatch.setattr(
        "fabric_tools.xmla_roles._kill_process_tree",
        lambda proc: kills.append(f"tree:{proc.pid}") or proc.kill(),
    )
    with pytest.raises(XmlaRolesError, match="timed out") as exc_info:
        _run_xmla_script(
            exe="powershell.exe",
            script=script,
            payload_json="{}",
            timeout=0.15,
        )
    assert exc_info.value.code == "timeout"
    assert exc_info.value.stage == "connecting"
    assert "connecting" in str(exc_info.value)
    assert any(k.startswith("tree:") for k in kills)


def test_run_xmla_script_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fabric_tools.xmla_roles import _run_xmla_script

    script = tmp_path / "xmla_role_members.ps1"
    script.write_text("# stub", encoding="utf-8")
    killed: list[str] = []

    class FakeProc:
        args = ["powershell.exe"]
        returncode = None
        pid = 99
        stdin = io.StringIO()
        stdout = io.StringIO("")
        stderr = io.StringIO("")
        _polls = 0

        def poll(self) -> int | None:
            self._polls += 1
            if self._polls == 1:
                raise KeyboardInterrupt
            return 1

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return None

        def kill(self) -> None:
            killed.append("kill")

    monkeypatch.setattr(
        "fabric_tools.xmla_roles.subprocess.Popen",
        lambda *a, **k: FakeProc(),
    )
    monkeypatch.setattr(
        "fabric_tools.xmla_roles._kill_process_tree",
        lambda proc: killed.append("tree") or proc.kill(),
    )
    with pytest.raises(XmlaRolesError, match="Cancelled") as exc_info:
        _run_xmla_script(
            exe="powershell.exe",
            script=script,
            payload_json="{}",
            timeout=30,
        )
    assert exc_info.value.code == "cancelled"
    assert "tree" in killed


def test_run_xmla_script_progress_callback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fabric_tools.xmla_roles import _run_xmla_script

    script = tmp_path / "xmla_role_members.ps1"
    script.write_text("# stub", encoding="utf-8")
    stages: list[str] = []

    class FakeProc:
        args = ["powershell.exe"]
        returncode = 0
        pid = 1
        stdin = io.StringIO()
        stdout = io.StringIO('{"ok":true,"changed":false,"message":"ok","roles":[]}')
        stderr = io.StringIO(
            "##fabric-tools## stage=connecting\n"
            "##fabric-tools## stage=loading_model\n"
            "other noise\n"
        )

        def poll(self) -> int | None:
            return 0

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        "fabric_tools.xmla_roles.subprocess.Popen",
        lambda *a, **k: FakeProc(),
    )
    result = _run_xmla_script(
        exe="powershell.exe",
        script=script,
        payload_json="{}",
        timeout=30,
        on_progress=stages.append,
    )
    assert stages == ["connecting", "loading_model"]
    assert "other noise" in result.stderr
    assert '"ok":true' in result.stdout
