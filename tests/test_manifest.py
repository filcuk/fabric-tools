"""Tests for deployment manifest (.ftdep) helpers and CLI inspect."""

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
    KIND_NOTEBOOK,
    ManifestError,
    delete_targets_from_manifest,
    format_inspect,
    format_inspect_line,
    item_id_overrides_from_results,
    list_manifest_paths,
    load_manifest,
    manifest_from_work_items,
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
    path = save_manifest(tmp_path / "deploy", built)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 1
    assert raw["kind"] == "notebook"
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
                "schemaVersion": 1,
                "kind": "semanticModel",
                "entries": [
                    {
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
    with pytest.raises(ManifestError, match="expected 'notebook'"):
        work_items_from_manifest(loaded)


def test_dataflow_gen1_kind_round_trip(tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    items = [WorkItem(Target(WS, ITEM), model)]
    built = manifest_from_work_items(
        items,
        kind=KIND_DATAFLOW_GEN1,
        display_names=["Sales"],
    )
    path = save_manifest(tmp_path / "df", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_DATAFLOW_GEN1
    work_items, names = work_items_from_manifest(
        loaded, expected_kind=KIND_DATAFLOW_GEN1
    )
    assert names == ["Sales"]
    assert work_items[0].file == model.resolve()


def test_dataflow_kind_round_trip(tmp_path: Path) -> None:
    folder = tmp_path / "Sales.Dataflow"
    folder.mkdir()
    items = [WorkItem(Target(WS, ITEM), folder)]
    built = manifest_from_work_items(
        items,
        kind=KIND_DATAFLOW,
        display_names=["Sales"],
    )
    path = save_manifest(tmp_path / "df2", built)
    loaded = load_manifest(path)
    assert loaded.kind == KIND_DATAFLOW
    work_items, names = work_items_from_manifest(loaded, expected_kind=KIND_DATAFLOW)
    assert names == ["Sales"]
    assert work_items[0].file == folder.resolve()


def test_delete_targets_from_manifest(tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    items = [
        WorkItem(Target(WS, ITEM), model),
        WorkItem(Target(WS, ITEM2), model),
    ]
    built = manifest_from_work_items(items, kind=KIND_DATAFLOW_GEN1)
    path = save_manifest(tmp_path / "df-del", built)
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
    path = save_manifest(tmp_path / "create-only", built)
    loaded = load_manifest(path)
    with pytest.raises(ManifestError, match="itemId"):
        delete_targets_from_manifest(loaded, expected_kind=KIND_NOTEBOOK)


def test_format_inspect_includes_kind() -> None:
    items = [WorkItem(Target(WS, ITEM), Path("a.ipynb"))]
    text = format_inspect(manifest_from_work_items(items), path=Path("m.ftdep"))
    assert "kind: notebook" in text
    assert WS in text


def test_format_inspect_line() -> None:
    items = [WorkItem(Target(WS, ITEM), Path("a.ipynb"))]
    line = format_inspect_line(
        manifest_from_work_items(items),
        path=Path("demo.ftdep"),
    )
    assert line == "demo.ftdep  kind=notebook  schemaVersion=1  entries=1"


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


def test_inspect_cli(tmp_path: Path) -> None:
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    save_manifest(
        tmp_path / "demo",
        manifest_from_work_items([WorkItem(Target(WS, ITEM), nb)]),
    )
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", "-m", str(tmp_path / "demo")])
    assert result.exit_code == 0
    assert "kind: notebook" in result.stdout
    assert "entries: 1" in result.stdout


def test_inspect_list_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    result = runner.invoke(app, ["inspect"])
    assert result.exit_code == 0
    assert "alpha.ftdep  kind=notebook  schemaVersion=1  entries=1" in result.stdout
    assert "beta.ftdep  kind=notebook  schemaVersion=1  entries=2" in result.stdout
    assert "broken.ftdep  error:" in result.stderr


def test_inspect_list_cwd_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["inspect"])
    assert result.exit_code == 0
    assert "No .ftdep manifests" in result.stdout


def test_inspect_missing_manifest() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", "-m", "does-not-exist-xyz"])
    assert result.exit_code == 1


def test_origin_manifest_v2_round_trip(tmp_path: Path) -> None:
    origin = Target(WS, ITEM)
    target = Target(WS, ITEM2)
    items = [WorkItem(target, None, origin=origin)]
    built = manifest_from_work_items(items)
    assert built.schema_version == 2
    path = save_manifest(tmp_path / "origin-deploy", built)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 2
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


def test_v1_manifest_still_loads(tmp_path: Path) -> None:
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
    loaded = load_manifest(path)
    assert loaded.schema_version == 1
    items, _ = work_items_from_manifest(loaded)
    assert items[0].file is not None
    assert items[0].origin is None
