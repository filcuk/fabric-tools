"""Smoke tests for CLI help surfaces added for Gen1 / delete."""

from __future__ import annotations

from typer.testing import CliRunner

from fabric_tools.cli import app


def test_root_help_lists_dataflow_gen1() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dataflow" in result.stdout
    assert "dataflow-gen1" in result.stdout
    assert "notebook" in result.stdout
    assert "pipeline" in result.stdout
    assert "udf" in result.stdout
    assert "semantic-model" in result.stdout
    assert "report" in result.stdout
    assert "paginated-report" in result.stdout
    assert "setup" in result.stdout
    assert "Local" in result.stdout
    assert "Fabric" in result.stdout


def test_root_help_orders_help_and_setup_first() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    help_idx = result.stdout.index("--help")
    version_idx = result.stdout.index("--version")
    interactive_idx = result.stdout.index("--interactive")
    assert help_idx < version_idx < interactive_idx
    assert "--install-completion" not in result.stdout
    assert "--show-completion" not in result.stdout

    # Panel titles use a leading box edge; avoid matching "Fabric" in the subtitle.
    local_idx = result.stdout.index("─ Local")
    fabric_idx = result.stdout.index("─ Fabric")
    setup_idx = result.stdout.index("setup")
    manifest_idx = result.stdout.index("manifest")
    env_idx = result.stdout.index("env")
    assert local_idx < setup_idx < manifest_idx < env_idx < fabric_idx

    # Command order comes from _BannerGroup.list_commands (not fragile substring scans:
    # "report" is a suffix of "paginated-report", "dataflow" of "dataflow-gen1", etc.).
    from typer.main import get_command

    names = get_command(app).list_commands(None)
    expected = [
        "setup",
        "manifest",
        "env",
        "inspect",
        "dataflow-gen1",
        "dataflow",
        "environment",
        "notebook",
        "org-app",
        "paginated-report",
        "pipeline",
        "report",
        "semantic-model",
        "udf",
    ]
    assert names[: len(expected)] == expected
    for name in expected:
        assert name in result.stdout


def test_setup_help_lists_update() -> None:
    result = CliRunner().invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "update" in result.stdout
    assert "install" in result.stdout
    assert "clean" in result.stdout
    assert "[-c] [-s]" in result.stdout
    assert "[--keep-files]" in result.stdout


def test_manifest_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["manifest", "--help"])
    assert result.exit_code == 0
    for name in ("inspect", "list", "delete", "move"):
        assert name in result.stdout
    assert "[-m <PATH>]" in result.stdout
    assert "-m <manifest>" in result.stdout
    assert "-m <manifest> <DEST>" in result.stdout


def test_inspect_help_lists_workspace_and_item_synopses() -> None:
    result = CliRunner().invoke(app, ["inspect", "--help"])
    assert result.exit_code == 0
    assert "list | get -t <workspaceId>" in result.stdout
    assert "list -t <workspaceId> | get -t <workspaceId:itemId>" in result.stdout


def test_inspect_workspace_help_lists_flag_synopses() -> None:
    result = CliRunner().invoke(app, ["inspect", "workspace", "--help"])
    assert result.exit_code == 0
    assert "[-f <FILTER>] [-i <TYPE>]" in result.stdout
    assert "-t <workspaceId>" in result.stdout


def test_inspect_item_help_lists_flag_synopses() -> None:
    result = CliRunner().invoke(app, ["inspect", "item", "--help"])
    assert result.exit_code == 0
    assert "-t <workspaceId> [-f <FILTER>] [-i <TYPE>]" in result.stdout
    assert "-t <workspaceId:itemId>" in result.stdout


def test_env_help_lists_argument_synopses() -> None:
    result = CliRunner().invoke(app, ["env", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "<NAME> <VALUE>" in result.stdout
    assert "<NAME>" in result.stdout


def test_help_puts_description_before_usage() -> None:
    result = CliRunner().invoke(app, ["setup", "update", "--help"])
    assert result.exit_code == 0
    description = "Check for a newer release"
    usage = "Usage:"
    assert description in result.stdout
    assert usage in result.stdout
    assert result.stdout.index(description) < result.stdout.index(usage)


def test_setup_update_help_lists_check() -> None:
    result = CliRunner().invoke(app, ["setup", "update", "--help"])
    assert result.exit_code == 0
    assert "--check" in result.stdout
    assert "-c" in result.stdout


def test_dataflow_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["dataflow", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout
    assert "Gen2" in result.stdout or "Dataflow" in result.stdout


def test_dataflow_gen1_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["dataflow-gen1", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout


def test_udf_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["udf", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout
    assert "User Data Function" in result.stdout


def test_pipeline_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["pipeline", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout
    assert "DataPipeline" in result.stdout


def test_pipeline_include_schedules_on_download_deploy_compare_not_delete() -> None:
    for cmd in ("download", "deploy", "compare"):
        result = CliRunner().invoke(app, ["pipeline", cmd, "--help"])
        assert result.exit_code == 0
        assert "--include-schedules" in result.stdout
        assert "-i" in result.stdout
    delete = CliRunner().invoke(app, ["pipeline", "delete", "--help"])
    assert delete.exit_code == 0
    assert "--include-schedules" not in delete.stdout


def test_deploy_kinds_help_lists_remap() -> None:
    for group in ("pipeline", "dataflow", "notebook", "udf"):
        deploy = CliRunner().invoke(app, [group, "deploy", "--help"])
        assert deploy.exit_code == 0
        assert "--remap" in deploy.stdout
        assert "-r" in deploy.stdout
        for cmd in ("download", "compare", "delete"):
            other = CliRunner().invoke(app, [group, cmd, "--help"])
            assert other.exit_code == 0
            assert "--remap" not in other.stdout


def test_semantic_model_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["semantic-model", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout
    assert "semantic model" in result.stdout.lower()


def test_semantic_model_deploy_help_lists_independent() -> None:
    deploy = CliRunner().invoke(app, ["semantic-model", "deploy", "--help"])
    assert deploy.exit_code == 0
    assert "--independent" in deploy.stdout
    assert "-i" in deploy.stdout
    delete = CliRunner().invoke(app, ["semantic-model", "delete", "--help"])
    assert delete.exit_code == 0
    assert "--independent" not in delete.stdout


def test_report_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["report", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout
    assert "report" in result.stdout.lower()


def test_paginated_report_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["paginated-report", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout
    assert "paginated" in result.stdout.lower() or ".rdl" in result.stdout.lower()


def test_report_independent_on_download_deploy_compare_not_delete() -> None:
    for cmd in ("download", "deploy", "compare"):
        result = CliRunner().invoke(app, ["report", cmd, "--help"])
        assert result.exit_code == 0
        assert "--independent" in result.stdout
    delete = CliRunner().invoke(app, ["report", "delete", "--help"])
    assert delete.exit_code == 0
    assert "--independent" not in delete.stdout


def test_udf_rejects_service_principal(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "t")
    monkeypatch.setenv("AZURE_CLIENT_ID", "c")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
    result = CliRunner().invoke(
        app,
        [
            "udf",
            "download",
            "-d",
            "-t",
            "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222",
        ],
    )
    assert result.exit_code != 0
    assert "service principal" in (result.stderr or result.stdout).lower()


def test_notebook_delete_help() -> None:
    result = CliRunner().invoke(app, ["notebook", "delete", "--help"])
    assert result.exit_code == 0
    assert "Soft-delete" in result.stdout or "delete" in result.stdout.lower()


def test_setup_status_user_facing_output(monkeypatch) -> None:
    installed = "1.2.3"
    running = "1.2.4"
    install_dir = r"C:\Users\demo\AppData\Local\fabric-tools\app"
    monkeypatch.setattr(
        "fabric_tools.path_setup.path_status",
        lambda: {
            "install_dir": install_dir,
            "bin_dir": install_dir,
            "exe_present": True,
            "cmd_present": False,
            "internal_present": False,
            "runtime_present": True,
            "bin_dir_on_user_path": True,
            "which_fabric_tools": "",
            "frozen": False,
            "cache_present": False,
            "install_state": "installed",
            "version": installed,
            "installed_version": installed,
            "running_version": running,
        },
    )
    monkeypatch.setenv("FABRIC_TOOLS_DISABLE_UPDATE_CHECK", "1")
    result = CliRunner().invoke(app, ["setup", "status"])
    assert result.exit_code == 0
    assert " Status  installed" in result.stdout
    assert f"Version  {installed}" in result.stdout
    assert " < " not in result.stdout
    assert "(up to date)" not in result.stdout
    assert f"Install  {install_dir}" in result.stdout
    assert "   PATH  registered" in result.stdout
    assert "open a new terminal" in result.stdout
    assert "  Cache  no" in result.stdout
    assert "setup clean" not in result.stdout
    assert "_internal" not in result.stdout
    assert "shutil.which" not in result.stdout
    assert "Status:" not in result.stdout
    assert "Install:" not in result.stdout


def test_setup_status_shows_update_available(monkeypatch) -> None:
    from fabric_tools.update_check import UpdateCheckResult

    installed = "1.2.3"
    latest = "1.2.4"
    install_dir = r"C:\Users\demo\AppData\Local\fabric-tools\app"
    monkeypatch.setattr(
        "fabric_tools.path_setup.path_status",
        lambda: {
            "install_dir": install_dir,
            "bin_dir": install_dir,
            "exe_present": True,
            "cmd_present": False,
            "internal_present": False,
            "runtime_present": True,
            "bin_dir_on_user_path": True,
            "which_fabric_tools": rf"{install_dir}\fabric-tools.exe",
            "frozen": False,
            "cache_present": False,
            "install_state": "installed",
            "version": installed,
            "installed_version": installed,
            "running_version": latest,
        },
    )
    monkeypatch.delenv("FABRIC_TOOLS_DISABLE_UPDATE_CHECK", raising=False)

    def fake_check(*, current=None, **_kwargs):
        assert current == installed
        return UpdateCheckResult(
            current=installed,
            latest=latest,
            update_available=True,
            release_url=f"https://example.test/releases/v{latest}",
            tag_name=f"v{latest}",
            prerelease=False,
            asset_url="https://example.test/fabric-tools.exe",
        )

    monkeypatch.setattr("fabric_tools.update_check.check_for_update", fake_check)
    monkeypatch.setattr(
        "fabric_tools.update_check.save_update_cache", lambda *_a, **_k: None
    )
    result = CliRunner().invoke(app, ["setup", "status"])
    assert result.exit_code == 0
    assert f"Version  {installed} < {latest}" in result.stdout


def test_setup_status_up_to_date_keeps_green_version(monkeypatch) -> None:
    from fabric_tools.update_check import UpdateCheckResult

    installed = "1.2.4"
    install_dir = r"C:\Users\demo\AppData\Local\fabric-tools\app"
    monkeypatch.setattr(
        "fabric_tools.path_setup.path_status",
        lambda: {
            "install_dir": install_dir,
            "bin_dir": install_dir,
            "exe_present": True,
            "cmd_present": False,
            "internal_present": False,
            "runtime_present": True,
            "bin_dir_on_user_path": True,
            "which_fabric_tools": "",
            "frozen": False,
            "cache_present": False,
            "install_state": "installed",
            "version": installed,
            "installed_version": installed,
            "running_version": installed,
        },
    )
    monkeypatch.delenv("FABRIC_TOOLS_DISABLE_UPDATE_CHECK", raising=False)

    def fake_check(*, current=None, **_kwargs):
        return UpdateCheckResult(
            current=installed,
            latest=installed,
            update_available=False,
            release_url=f"https://example.test/releases/v{installed}",
            tag_name=f"v{installed}",
            prerelease=False,
            asset_url=None,
        )

    monkeypatch.setattr("fabric_tools.update_check.check_for_update", fake_check)
    monkeypatch.setattr(
        "fabric_tools.update_check.save_update_cache", lambda *_a, **_k: None
    )
    result = CliRunner().invoke(app, ["setup", "status"])
    assert result.exit_code == 0
    assert f"Version  {installed} (up to date)" in result.stdout
    assert " < " not in result.stdout


def test_setup_status_update_check_failure_keeps_version(monkeypatch) -> None:
    from fabric_tools.update_check import UpdateCheckError

    installed = "1.2.3"
    install_dir = r"C:\Users\demo\AppData\Local\fabric-tools\app"
    monkeypatch.setattr(
        "fabric_tools.path_setup.path_status",
        lambda: {
            "install_dir": install_dir,
            "bin_dir": install_dir,
            "exe_present": True,
            "cmd_present": False,
            "internal_present": False,
            "runtime_present": True,
            "bin_dir_on_user_path": False,
            "which_fabric_tools": "",
            "frozen": False,
            "cache_present": False,
            "install_state": "installed",
            "version": installed,
            "installed_version": installed,
            "running_version": installed,
        },
    )
    monkeypatch.delenv("FABRIC_TOOLS_DISABLE_UPDATE_CHECK", raising=False)

    def boom(*, current=None, **_kwargs):
        raise UpdateCheckError("failed to reach GitHub")

    monkeypatch.setattr("fabric_tools.update_check.check_for_update", boom)
    result = CliRunner().invoke(app, ["setup", "status"])
    assert result.exit_code == 0
    assert f"Version  {installed} (update check failed)" in result.stdout
    assert " < " not in result.stdout
    assert "(up to date)" not in result.stdout
    assert "failed to reach GitHub" not in result.stdout


def test_setup_status_update_check_timeout_note(monkeypatch) -> None:
    import httpx

    from fabric_tools.update_check import UpdateCheckError

    installed = "1.2.3"
    install_dir = r"C:\Users\demo\AppData\Local\fabric-tools\app"
    monkeypatch.setattr(
        "fabric_tools.path_setup.path_status",
        lambda: {
            "install_dir": install_dir,
            "bin_dir": install_dir,
            "exe_present": True,
            "cmd_present": False,
            "internal_present": False,
            "runtime_present": True,
            "bin_dir_on_user_path": False,
            "which_fabric_tools": "",
            "frozen": False,
            "cache_present": False,
            "install_state": "installed",
            "version": installed,
            "installed_version": installed,
            "running_version": installed,
        },
    )
    monkeypatch.delenv("FABRIC_TOOLS_DISABLE_UPDATE_CHECK", raising=False)

    def boom(*, current=None, **_kwargs):
        raise UpdateCheckError(
            "failed to reach GitHub: timed out"
        ) from httpx.TimeoutException("timed out")

    monkeypatch.setattr("fabric_tools.update_check.check_for_update", boom)
    result = CliRunner().invoke(app, ["setup", "status"])
    assert result.exit_code == 0
    assert f"Version  {installed} (update check timeout)" in result.stdout
    assert "(update check failed)" not in result.stdout


def test_setup_status_hints_clean_when_cache_present(monkeypatch) -> None:
    installed = "1.2.4"
    install_dir = r"C:\Users\demo\AppData\Local\fabric-tools\app"
    monkeypatch.setattr(
        "fabric_tools.path_setup.path_status",
        lambda: {
            "install_dir": install_dir,
            "bin_dir": install_dir,
            "exe_present": True,
            "cmd_present": False,
            "internal_present": False,
            "runtime_present": True,
            "bin_dir_on_user_path": True,
            "which_fabric_tools": rf"{install_dir}\fabric-tools.exe",
            "frozen": False,
            "cache_present": True,
            "install_state": "installed",
            "version": installed,
            "installed_version": installed,
            "running_version": installed,
        },
    )
    monkeypatch.setenv("FABRIC_TOOLS_DISABLE_UPDATE_CHECK", "1")
    result = CliRunner().invoke(app, ["setup", "status"])
    assert result.exit_code == 0
    assert "  Cache  yes" in result.stdout
    assert "setup clean" in result.stdout


def test_setup_clean_removes_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        "fabric_tools.path_setup.clean_onefile_caches",
        lambda: {"cleaned": True, "scheduled": False},
    )
    result = CliRunner().invoke(app, ["setup", "clean"])
    assert result.exit_code == 0
    assert "Removed onefile extract cache" in result.stdout
