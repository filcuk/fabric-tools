"""Tests for deployment manifest (.ftdep) helpers and CLI inspect."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fabric_tools.cli import app, _resolve_notebook_inputs, _write_manifest_after_success
from fabric_tools.manifest import (
    ManifestError,
    format_inspect,
    item_id_overrides_from_results,
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


def test_format_inspect_includes_kind() -> None:
    items = [WorkItem(Target(WS, ITEM), Path("a.ipynb"))]
    text = format_inspect(manifest_from_work_items(items), path=Path("m.ftdep"))
    assert "kind: notebook" in text
    assert WS in text


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
    items, names, has_t, has_f = _resolve_notebook_inputs(
        CommandMode.COMPARE,
        target_values=None,
        file_values=None,
        dry_run=False,
        names=None,
        manifest=str(tmp_path / "test"),
    )
    assert has_t and has_f
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


def test_inspect_missing_manifest() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", "-m", "does-not-exist-xyz"])
    assert result.exit_code == 1
