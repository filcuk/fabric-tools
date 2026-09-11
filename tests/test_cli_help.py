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

    # Panel titles use a leading box edge; avoid matching "Fabric" in the subtitle.
    local_idx = result.stdout.index("─ Local")
    fabric_idx = result.stdout.index("─ Fabric")
    setup_idx = result.stdout.index("setup")
    inspect_idx = result.stdout.index("inspect")
    env_idx = result.stdout.index("env")
    assert local_idx < setup_idx < inspect_idx < env_idx < fabric_idx

    # Command order comes from _BannerGroup.list_commands (not fragile substring scans:
    # "report" is a suffix of "paginated-report", "dataflow" of "dataflow-gen1", etc.).
    from typer.main import get_command

    names = get_command(app).list_commands(None)
    expected = [
        "setup",
        "inspect",
        "env",
        "dataflow-gen1",
        "dataflow",
        "notebook",
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
