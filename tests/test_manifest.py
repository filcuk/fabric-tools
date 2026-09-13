"""Tests for deployment manifest (.ftdep) helpers and CLI manifest commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fabric_tools.cli import (
    _resolve_notebook_inputs,
    _write_manifest_after_success,
    app,
)
from fabric_tools.client import FabricApiError
from fabric_tools.manifest import (
    KIND_DATAFLOW,
    KIND_DATAFLOW_GEN1,
    KIND_ENVIRONMENT,
    KIND_NOTEBOOK,
    KIND_ORG_APP,
    KIND_PACK,
    KIND_PAGINATED_REPORT,
    KIND_PIPELINE,
    KIND_REPORT,
    KIND_SEMANTIC_MODEL,
    KIND_UDF,
    DeploymentManifest,
    ManifestEntry,
    ManifestError,
    delete_manifest_file,
    delete_targets_from_manifest,
    effective_remap_path,
    entry_guid_maps_from_manifest,
    format_inspect,
    format_inspect_line,
    group_pack_entries_by_kind,
    item_id_overrides_from_results,
    list_manifest_paths,
    load_manifest,
    manifest_from_work_items,
    move_manifest_file,
    resolve_inspect_target,
    resolve_manifest_path,
    save_manifest,
    work_items_from_manifest,
)
from fabric_tools.notebook.ops import OpResult
from fabric_tools.parsing import CommandMode, Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
ITEM = "22222222-2222-2222-2222-222222222222"
ITEM2 = "33333333-3333-3333-3333-333333333333"


def test_resolve_manifest_path_appends_suffix() -> None:
    assert resolve_manifest_path("test").name == "test.ftdep"
    assert resolve_manifest_path("test.ftdep").name == "test.ftdep"
    assert resolve_manifest_path(Path("dir") / "demo").name == "demo.ftdep"


def test_save_load_round_trip_relative_paths(tmp_path: Path) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    items = [WorkItem(Target(WS, ITEM), nb)]
    built = manifest_from_work_items(items, display_names=["ETL"])
    path, written = save_manifest(tmp_path / "deploy", built)
    assert written

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 3
    assert raw["kind"] == "pack"
    assert raw["entries"][0]["kind"] == "notebook"
    assert raw["entries"][0]["file"] == "etl.ipynb"
    assert raw["entries"][0]["displayName"] == "ETL"

    loaded = load_manifest(path)
    work_items, names = work_items_from_manifest(loaded)
    assert names == ["ETL"]
    assert work_items[0].target is not None
    assert work_items[0].target.item_id == ITEM
    assert work_items[0].file == nb.resolve()


def test_create_guid_backfill() -> None:
    items = [WorkItem(Target(WS, None), Path("a.ipynb"))]
    built = manifest_from_work_items(
        items,
        item_id_overrides=[ITEM2],
        display_names=["A"],
    )
    assert built.entries[0].item_id == ITEM2


def test_wrong_kind_rejected(tmp_path: Path) -> None:
    path = tmp_path / "x.ftdep"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 3,
                "kind": "pack",
                "entries": [
                    {
                        "kind": "semantic-model",
                        "workspaceId": WS,
                        "itemId": ITEM,
                        "file": "model.bim",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_manifest(path)
    with pytest.raises(ManifestError, match="expected all 'notebook'"):
        work_items_from_manifest(loaded)


def test_report_kind_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "Sales.Report"
    folder.mkdir()
    items = [WorkItem(Target(WS, ITEM), folder)]
    built = manifest_from_work_items(
        items,
        kind=KIND_REPORT,
        display_names=["Sales"],
    )
    path, _ = save_manifest(tmp_path / "rpt", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_REPORT
    work_items, names = work_items_from_manifest(loaded, expected_kind=KIND_REPORT)
    assert names == ["Sales"]
    assert work_items[0].file == folder.resolve()


def test_semantic_model_kind_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "Sales.SemanticModel"
    folder.mkdir()
    items = [WorkItem(Target(WS, ITEM), folder)]
    built = manifest_from_work_items(
        items,
        kind=KIND_SEMANTIC_MODEL,
        display_names=["Sales"],
    )
    path, _ = save_manifest(tmp_path / "sm", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_SEMANTIC_MODEL
    work_items, names = work_items_from_manifest(
        loaded, expected_kind=KIND_SEMANTIC_MODEL
    )
    assert names == ["Sales"]
    assert work_items[0].file == folder.resolve()


def test_report_semantic_model_id_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "Sales.Report"
    folder.mkdir()
    built = DeploymentManifest(
        kind=KIND_PACK,
        entries=(
            ManifestEntry(
                kind=KIND_REPORT,
                workspace_id=WS,
                item_id=ITEM,
                file=folder,
                display_name="Sales",
                semantic_model_id=ITEM2,
            ),
        ),
    )
    path, _ = save_manifest(tmp_path / "rpt_sm", built)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["entries"][0]["semanticModelId"] == ITEM2
    loaded = load_manifest(path)
    assert loaded.entries[0].semantic_model_id == ITEM2
    text = format_inspect(loaded, path=path)
    assert f"semanticModelId={ITEM2}" in text


def test_dataflow_gen1_kind_round_trip(tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    items = [WorkItem(Target(WS, ITEM), model)]
    built = manifest_from_work_items(
        items,
        kind=KIND_DATAFLOW_GEN1,
        display_names=["Sales"],
    )
    path, _ = save_manifest(tmp_path / "df", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_DATAFLOW_GEN1
    work_items, names = work_items_from_manifest(
        loaded, expected_kind=KIND_DATAFLOW_GEN1
    )
    assert names == ["Sales"]
    assert work_items[0].file == model.resolve()


def test_paginated_report_kind_round_trip(tmp_path: Path) -> None:
    rdl = tmp_path / "Sales.rdl"
    rdl.write_text("<Report />", encoding="utf-8")
    items = [WorkItem(Target(WS, ITEM), rdl)]
    built = manifest_from_work_items(
        items,
        kind=KIND_PAGINATED_REPORT,
        display_names=["Sales"],
    )
    path, _ = save_manifest(tmp_path / "pr", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_PAGINATED_REPORT
    work_items, names = work_items_from_manifest(
        loaded, expected_kind=KIND_PAGINATED_REPORT
    )
    assert names == ["Sales"]
    assert work_items[0].file == rdl.resolve()


def test_dataflow_kind_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "Sales.Dataflow"
    folder.mkdir()
    items = [WorkItem(Target(WS, ITEM), folder)]
    built = manifest_from_work_items(
        items,
        kind=KIND_DATAFLOW,
        display_names=["Sales"],
    )
    path, _ = save_manifest(tmp_path / "df2", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_DATAFLOW
    work_items, names = work_items_from_manifest(loaded, expected_kind=KIND_DATAFLOW)
    assert names == ["Sales"]
    assert work_items[0].file == folder.resolve()


def test_org_app_kind_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "Sales.OrgApp"
    folder.mkdir()
    items = [WorkItem(Target(WS, ITEM), folder)]
    built = manifest_from_work_items(
        items,
        kind=KIND_ORG_APP,
        display_names=["Sales"],
    )
    path, _ = save_manifest(tmp_path / "org-app", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_ORG_APP
    work_items, names = work_items_from_manifest(loaded, expected_kind=KIND_ORG_APP)
    assert names == ["Sales"]
    assert work_items[0].file == folder.resolve()


def test_environment_kind_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "Dev.Environment"
    folder.mkdir()
    items = [WorkItem(Target(WS, ITEM), folder)]
    built = manifest_from_work_items(
        items,
        kind=KIND_ENVIRONMENT,
        display_names=["Dev"],
    )
    path, _ = save_manifest(tmp_path / "environment", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_ENVIRONMENT
    work_items, names = work_items_from_manifest(loaded, expected_kind=KIND_ENVIRONMENT)
    assert names == ["Dev"]
    assert work_items[0].file == folder.resolve()


def test_udf_kind_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "Demo.UserDataFunction"
    folder.mkdir()
    items = [WorkItem(Target(WS, ITEM), folder)]
    built = manifest_from_work_items(
        items,
        kind=KIND_UDF,
        display_names=["Demo"],
    )
    path, _ = save_manifest(tmp_path / "udf", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_UDF
    work_items, names = work_items_from_manifest(loaded, expected_kind=KIND_UDF)
    assert names == ["Demo"]
    assert work_items[0].file == folder.resolve()


def test_pipeline_kind_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "ETL.DataPipeline"
    folder.mkdir()
    items = [WorkItem(Target(WS, ITEM), folder)]
    built = manifest_from_work_items(
        items,
        kind=KIND_PIPELINE,
        display_names=["ETL"],
    )
    path, _ = save_manifest(tmp_path / "pipe", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_PACK
    assert loaded.entries[0].kind == KIND_PIPELINE
    work_items, names = work_items_from_manifest(loaded, expected_kind=KIND_PIPELINE)
    assert names == ["ETL"]
    assert work_items[0].file == folder.resolve()


def test_delete_targets_from_manifest(tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    items = [
        WorkItem(Target(WS, ITEM), model),
        WorkItem(Target(WS, ITEM2), model),
    ]
    built = manifest_from_work_items(items, kind=KIND_DATAFLOW_GEN1)
    path, _ = save_manifest(tmp_path / "df-del", built)
    loaded = load_manifest(path)
    delete_items = delete_targets_from_manifest(
        loaded, expected_kind=KIND_DATAFLOW_GEN1
    )
    assert len(delete_items) == 2
    assert delete_items[0].file is None
    assert delete_items[0].target is not None
    assert delete_items[0].target.item_id == ITEM


def test_delete_targets_from_manifest_requires_item_id(tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    items = [WorkItem(Target(WS, None), model)]
    built = manifest_from_work_items(items, kind=KIND_NOTEBOOK)
    path, _ = save_manifest(tmp_path / "create-only", built)
    loaded = load_manifest(path)
    with pytest.raises(ManifestError, match="itemId"):
        delete_targets_from_manifest(loaded, expected_kind=KIND_NOTEBOOK)


def test_format_inspect_includes_kind() -> None:
    items = [WorkItem(Target(WS, ITEM), Path("a.ipynb"))]
    text = format_inspect(manifest_from_work_items(items), path=Path("m.ftdep"))
    assert "kind: pack" in text
    assert "[notebook]" in text
    assert WS in text


def test_format_inspect_line() -> None:
    items = [WorkItem(Target(WS, ITEM), Path("a.ipynb"))]
    line = format_inspect_line(
        manifest_from_work_items(items),
        path=Path("demo.ftdep"),
    )
    assert line == "demo.ftdep  kind=pack[notebook]  schemaVersion=3  entries=1"


def test_list_manifest_paths(tmp_path: Path) -> None:
    (tmp_path / "b.ftdep").write_text("{}", encoding="utf-8")
    (tmp_path / "a.ftdep").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    names = [p.name for p in list_manifest_paths(tmp_path)]
    assert names == ["a.ftdep", "b.ftdep"]


def test_item_id_overrides_from_results() -> None:
    results = [
        OpResult(True, "created", WS, ITEM2),
        OpResult(False, "failed", WS, None),
    ]
    assert item_id_overrides_from_results(results) == [ITEM2, None]


def test_resolve_notebook_inputs_from_manifest(tmp_path: Path) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    save_manifest(
        tmp_path / "test",
        manifest_from_work_items(
            [WorkItem(Target(WS, ITEM), nb)],
            display_names=["ETL"],
        ),
    )
    items, names, has_t, has_f, has_o = _resolve_notebook_inputs(
        CommandMode.COMPARE,
        target_values=None,
        file_values=None,
        origin_values=None,
        dry_run=False,
        names=None,
        manifest=str(tmp_path / "test"),
    )
    assert has_t and has_f and not has_o
    assert names == ["ETL"]
    assert items[0].file == nb.resolve()


def test_write_manifest_after_success_skips_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    items = [WorkItem(Target(WS, ITEM), tmp_path / "a.ipynb")]
    _write_manifest_after_success(
        "out",
        items,
        display_names=None,
        op_results=[OpResult(False, "nope", WS, ITEM)],
    )
    assert not (tmp_path / "out.ftdep").exists()


def test_write_manifest_after_success_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    nb = tmp_path / "a.ipynb"
    nb.write_text("{}", encoding="utf-8")
    items = [WorkItem(Target(WS, None), nb)]
    _write_manifest_after_success(
        "out",
        items,
        display_names=["A"],
        op_results=[OpResult(True, "created", WS, ITEM2)],
    )
    data = json.loads((tmp_path / "out.ftdep").read_text(encoding="utf-8"))
    assert data["entries"][0]["itemId"] == ITEM2


def test_save_manifest_skips_identical_content(tmp_path: Path) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    items = [WorkItem(Target(WS, ITEM), nb)]
    built = manifest_from_work_items(items, display_names=["ETL"])
    path, written = save_manifest(tmp_path / "deploy", built)
    assert written
    mtime = path.stat().st_mtime_ns
    path2, written_again = save_manifest(tmp_path / "deploy", built)
    assert path2 == path
    assert not written_again
    assert path.stat().st_mtime_ns == mtime


def test_write_manifest_after_success_silent_when_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    nb = tmp_path / "a.ipynb"
    nb.write_text("{}", encoding="utf-8")
    items = [WorkItem(Target(WS, ITEM), nb)]
    built = manifest_from_work_items(items, display_names=["A"])
    save_manifest("out", built)
    _write_manifest_after_success(
        "out",
        items,
        display_names=["A"],
        op_results=[OpResult(True, "ok", WS, ITEM)],
    )
    assert "Wrote manifest:" not in capsys.readouterr().out


def test_dry_run_writes_manifest_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    nb = tmp_path / "etl.ipynb"
    nb.write_text(
        json.dumps({"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}),
        encoding="utf-8",
    )

    class OkClient:
        def ensure_authenticated(self) -> None:
            return None

        def get_workspace(self, workspace_id: str) -> dict:
            return {"id": workspace_id, "displayName": "Dev"}

        def get_item(self, workspace_id: str, item_id: str) -> dict:
            return {
                "id": item_id,
                "workspaceId": workspace_id,
                "displayName": "NB",
                "type": "Notebook",
            }

        def close(self) -> None:
            return None

    monkeypatch.setattr("fabric_tools.client.FabricClient", OkClient)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "notebook",
            "deploy",
            "-d",
            "-t",
            f"{WS}:{ITEM}",
            "-f",
            str(nb),
            "-m",
            "setup",
        ],
    )
    assert result.exit_code == 0
    assert (tmp_path / "setup.ftdep").exists()
    assert "Wrote manifest:" in result.stdout
    data = json.loads((tmp_path / "setup.ftdep").read_text(encoding="utf-8"))
    assert data["entries"][0]["workspaceId"] == WS
    assert data["entries"][0]["itemId"] == ITEM


def test_dry_run_skips_manifest_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    nb = tmp_path / "etl.ipynb"
    nb.write_text(
        json.dumps({"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}),
        encoding="utf-8",
    )

    class BadClient:
        def ensure_authenticated(self) -> None:
            return None

        def get_workspace(self, workspace_id: str) -> dict:
            raise FabricApiError(
                "missing", status_code=404, error_code="WorkspaceNotFound"
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr("fabric_tools.client.FabricClient", BadClient)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "notebook",
            "deploy",
            "-d",
            "-t",
            f"{WS}:{ITEM}",
            "-f",
            str(nb),
            "-m",
            "setup",
        ],
    )
    assert result.exit_code != 0
    assert not (tmp_path / "setup.ftdep").exists()


def _save_simple_manifest(directory: Path, stem: str) -> Path:
    nb = directory / "etl.ipynb"
    if not nb.exists():
        nb.write_text("{}", encoding="utf-8")
    path, _ = save_manifest(
        directory / stem,
        manifest_from_work_items([WorkItem(Target(WS, ITEM), nb)]),
    )
    return path


def test_resolve_inspect_target_directory(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    assert resolve_inspect_target(jobs) == jobs
    assert resolve_inspect_target(str(jobs)) == jobs


def test_resolve_inspect_target_stem(tmp_path: Path) -> None:
    assert resolve_inspect_target(tmp_path / "demo").name == "demo.ftdep"


def test_delete_manifest_file(tmp_path: Path) -> None:
    path = _save_simple_manifest(tmp_path, "demo")
    deleted = delete_manifest_file(path)
    assert deleted == path
    assert not path.exists()


def test_move_manifest_file_creates_parents(tmp_path: Path) -> None:
    source = _save_simple_manifest(tmp_path, "demo")
    dest = tmp_path / "subdir" / "renamed.ftdep"
    move_manifest_file(source, dest)
    assert not source.exists()
    assert dest.is_file()


def test_inspect_cli(tmp_path: Path) -> None:
    _save_simple_manifest(tmp_path, "demo")
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "inspect", "-m", str(tmp_path / "demo")])
    assert result.exit_code == 0
    assert "kind: pack" in result.stdout
    assert "[notebook]" in result.stdout
    assert "entries: 1" in result.stdout


def test_inspect_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    save_manifest(
        tmp_path / "alpha",
        manifest_from_work_items([WorkItem(Target(WS, ITEM), nb)]),
    )
    save_manifest(
        tmp_path / "beta",
        manifest_from_work_items(
            [
                WorkItem(Target(WS, ITEM), nb),
                WorkItem(Target(WS, ITEM2), nb),
            ]
        ),
    )
    (tmp_path / "broken.ftdep").write_text("{not-json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "inspect"])
    assert result.exit_code == 0
    assert (
        "alpha.ftdep  kind=pack[notebook]  schemaVersion=3  entries=1" in result.stdout
    )
    assert (
        "beta.ftdep  kind=pack[notebook]  schemaVersion=3  entries=2" in result.stdout
    )
    assert "broken.ftdep  error:" in result.stderr


def test_inspect_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _save_simple_manifest(tmp_path, "cwd_only")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    _save_simple_manifest(jobs, "alpha")
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "inspect", "-m", str(jobs)])
    assert result.exit_code == 0
    assert (
        "alpha.ftdep  kind=pack[notebook]  schemaVersion=3  entries=1" in result.stdout
    )
    assert "cwd_only" not in result.stdout


def test_inspect_folder_empty(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "inspect", "-m", str(jobs)])
    assert result.exit_code == 0
    assert "No .ftdep manifests" in result.stdout
    assert "jobs" in result.stdout


def test_inspect_cwd_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "inspect"])
    assert result.exit_code == 0
    assert "No .ftdep manifests" in result.stdout


def test_inspect_missing_manifest() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "inspect", "-m", "does-not-exist-xyz"])
    assert result.exit_code == 1


def test_list_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _save_simple_manifest(tmp_path, "alpha")
    (tmp_path / "broken.ftdep").write_text("{not-json", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "list"])
    assert result.exit_code == 0
    assert "alpha.ftdep" in result.stdout
    assert "broken.ftdep" in result.stdout
    assert "kind=" not in result.stdout


def test_list_cwd_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "list"])
    assert result.exit_code == 0
    assert "No .ftdep manifests" in result.stdout


def test_manifest_delete_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _save_simple_manifest(tmp_path, "demo")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "delete", "-s", "-m", "demo"])
    assert result.exit_code == 0
    assert not path.exists()
    assert "Deleted local manifest file" in result.stdout


def test_manifest_delete_confirm_decline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _save_simple_manifest(tmp_path, "demo")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "delete", "-m", "demo"], input="n\n")
    assert result.exit_code == 1
    assert path.exists()


def test_manifest_delete_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "delete", "-s", "-m", "missing"])
    assert result.exit_code == 1
    assert "manifest not found" in result.output


def test_manifest_move_silent_dest_stem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _save_simple_manifest(tmp_path, "demo")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["manifest", "move", "-s", "-m", "demo", "subdir/renamed"],
    )
    assert result.exit_code == 0
    assert not source.exists()
    dest = tmp_path / "subdir" / "renamed.ftdep"
    assert dest.is_file()
    assert "Moved local manifest file" in result.stdout


def test_manifest_move_overwrite_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    source, _ = save_manifest(
        tmp_path / "alpha",
        manifest_from_work_items([WorkItem(Target(WS, ITEM), nb)]),
    )
    dest, _ = save_manifest(
        tmp_path / "beta",
        manifest_from_work_items([WorkItem(Target(WS, ITEM2), nb)]),
    )
    source_text = source.read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "move", "-s", "-m", "alpha", "beta"])
    assert result.exit_code == 0
    assert not source.exists()
    assert dest.read_text(encoding="utf-8") == source_text
    assert ITEM in dest.read_text(encoding="utf-8")
    assert ITEM2 not in dest.read_text(encoding="utf-8")


def test_manifest_move_confirm_decline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _save_simple_manifest(tmp_path, "demo")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["manifest", "move", "-m", "demo", "other"],
        input="n\n",
    )
    assert result.exit_code == 1
    assert source.exists()
    assert not (tmp_path / "other.ftdep").exists()


def test_manifest_move_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["manifest", "move", "-s", "-m", "missing", "dest"])
    assert result.exit_code == 1
    assert "manifest not found" in result.output


def test_origin_manifest_round_trip(tmp_path: Path) -> None:
    origin = Target(WS, ITEM)
    target = Target(WS, ITEM2)
    items = [WorkItem(target, None, origin=origin)]
    built = manifest_from_work_items(items)
    assert built.schema_version == 3
    assert built.kind == KIND_PACK
    path, _ = save_manifest(tmp_path / "origin-deploy", built)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 3
    assert raw["kind"] == "pack"
    assert raw["entries"][0]["kind"] == "notebook"
    assert raw["entries"][0]["originWorkspaceId"] == WS
    assert raw["entries"][0]["originItemId"] == ITEM
    assert "file" not in raw["entries"][0]

    loaded = load_manifest(path)
    work_items, _ = work_items_from_manifest(loaded)
    assert work_items[0].file is None
    assert work_items[0].origin is not None
    assert work_items[0].origin.item_id == ITEM
    assert "<-" in format_inspect(loaded)
    assert ITEM in format_inspect(loaded)


def test_legacy_v1_manifest_rejected(tmp_path: Path) -> None:
    path = tmp_path / "legacy.ftdep"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "notebook",
                "entries": [
                    {
                        "workspaceId": WS,
                        "itemId": ITEM,
                        "file": "etl.ipynb",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="unsupported schemaVersion 1"):
        load_manifest(path)


def test_pack_remap_paths_round_trip(tmp_path: Path) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    pack_map = tmp_path / "pack.remap.json"
    entry_map = tmp_path / "entry.remap.json"
    src = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    dst = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    pack_map.write_text(json.dumps({src: dst}), encoding="utf-8")
    entry_map.write_text(
        json.dumps({src: "cccccccc-cccc-cccc-cccc-cccccccccccc"}),
        encoding="utf-8",
    )
    built = DeploymentManifest(
        kind=KIND_PACK,
        remap=pack_map,
        entries=(
            ManifestEntry(
                kind=KIND_NOTEBOOK,
                workspace_id=WS,
                item_id=ITEM,
                file=nb,
                remap=entry_map,
            ),
            ManifestEntry(
                kind=KIND_PIPELINE,
                workspace_id=WS,
                item_id=ITEM2,
                file=nb,
            ),
        ),
    )
    path, _ = save_manifest(tmp_path / "pack", built)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["remap"] == "pack.remap.json"
    assert raw["entries"][0]["remap"] == "entry.remap.json"
    assert "remap" not in raw["entries"][1]

    loaded = load_manifest(path)
    assert effective_remap_path(loaded, loaded.entries[0]) == entry_map.resolve()
    assert effective_remap_path(loaded, loaded.entries[1]) == pack_map.resolve()
    specs = entry_guid_maps_from_manifest(loaded)
    assert specs[0] is not None
    assert specs[0].mapping[src] == "cccccccc-cccc-cccc-cccc-cccccccccccc"
    assert specs[1] is not None
    assert specs[1].mapping[src] == dst


def test_pack_missing_remap_file_fails(tmp_path: Path) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    built = DeploymentManifest(
        kind=KIND_PACK,
        remap=tmp_path / "missing.remap.json",
        entries=(
            ManifestEntry(
                kind=KIND_NOTEBOOK,
                workspace_id=WS,
                item_id=ITEM,
                file=nb,
            ),
        ),
    )
    path, _ = save_manifest(tmp_path / "pack", built)
    loaded = load_manifest(path)
    with pytest.raises(ManifestError, match="remap failed"):
        entry_guid_maps_from_manifest(loaded)


def test_group_pack_entries_orders_model_before_report() -> None:
    entries = (
        ManifestEntry(
            kind=KIND_NOTEBOOK, workspace_id=WS, item_id=ITEM, file=Path("a")
        ),
        ManifestEntry(kind=KIND_REPORT, workspace_id=WS, item_id=ITEM, file=Path("b")),
        ManifestEntry(
            kind=KIND_SEMANTIC_MODEL, workspace_id=WS, item_id=ITEM, file=Path("c")
        ),
        ManifestEntry(
            kind=KIND_ENVIRONMENT, workspace_id=WS, item_id=ITEM, file=Path("env")
        ),
        ManifestEntry(kind=KIND_ORG_APP, workspace_id=WS, item_id=ITEM, file=Path("d")),
    )
    groups = group_pack_entries_by_kind(entries)
    assert [kind for kind, _ in groups] == [
        KIND_SEMANTIC_MODEL,
        KIND_REPORT,
        KIND_ENVIRONMENT,
        KIND_ORG_APP,
        KIND_NOTEBOOK,
    ]
    rev = group_pack_entries_by_kind(entries, reverse=True)
    assert [kind for kind, _ in rev] == [
        KIND_NOTEBOOK,
        KIND_ORG_APP,
        KIND_ENVIRONMENT,
        KIND_REPORT,
        KIND_SEMANTIC_MODEL,
    ]


def test_mixed_pack_rejected_by_notebook_command(tmp_path: Path) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    built = DeploymentManifest(
        kind=KIND_PACK,
        entries=(
            ManifestEntry(
                kind=KIND_NOTEBOOK,
                workspace_id=WS,
                item_id=ITEM,
                file=nb,
            ),
            ManifestEntry(
                kind=KIND_DATAFLOW,
                workspace_id=WS,
                item_id=ITEM2,
                file=nb,
            ),
        ),
    )
    path, _ = save_manifest(tmp_path / "mixed", built)
    loaded = load_manifest(path)
    with pytest.raises(ManifestError, match="fabric-tools pack"):
        work_items_from_manifest(loaded, expected_kind=KIND_NOTEBOOK)
