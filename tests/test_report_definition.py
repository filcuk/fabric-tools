"""Tests for report definition pack/unpack and definition.pbir bind helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabric_tools.report.definition import (
    DefinitionError,
    ReportFormat,
    detect_format,
    display_name_from_path,
    load_pbir,
    pack_definition,
    parse_dataset_reference,
    resolve_local_join,
    rewrite_pbir_to_by_connection,
    unpack_definition,
    validate_local_report,
)


def _pbir_by_path(relative: str = "../Sales.SemanticModel") -> str:
    return json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/item/"
                "report/definitionProperties/2.0.0/schema.json"
            ),
            "version": "4.0",
            "datasetReference": {"byPath": {"path": relative}},
        }
    )


def _pbir_by_connection(model_id: str) -> str:
    return json.dumps(
        {
            "version": "4.0",
            "datasetReference": {
                "byConnection": {
                    "connectionString": f"semanticmodelid={model_id}",
                }
            },
        }
    )


def _write_report(
    folder: Path,
    *,
    pbir: str | None = None,
    legacy: bool = False,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "definition.pbir").write_text(
        pbir or _pbir_by_connection("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        encoding="utf-8",
    )
    if legacy:
        (folder / "report.json").write_text('{"legacy": true}\n', encoding="utf-8")
    else:
        (folder / "definition").mkdir(parents=True, exist_ok=True)
        (folder / "definition" / "report.json").write_text(
            '{"version": "1.0"}\n', encoding="utf-8"
        )
        (folder / "definition" / "pages").mkdir(parents=True, exist_ok=True)
        (folder / "definition" / "pages" / "pages.json").write_text(
            '{"pages": []}\n', encoding="utf-8"
        )
    return folder


def _write_semantic_model(folder: Path) -> Path:
    (folder / "definition").mkdir(parents=True)
    (folder / "definition.pbism").write_text(
        json.dumps({"version": "5.0"}), encoding="utf-8"
    )
    (folder / "definition" / "model.tmdl").write_text("model Sales\n", encoding="utf-8")
    return folder


def test_display_name_and_validate(tmp_path: Path) -> None:
    folder = _write_report(tmp_path / "Sales.Report")
    assert display_name_from_path(folder) == "Sales"
    assert validate_local_report(folder) == folder
    assert detect_format(folder) is ReportFormat.PBIR


def test_pack_unpack_round_trip(tmp_path: Path) -> None:
    src = _write_report(tmp_path / "Sales.Report")
    definition = pack_definition(src)
    assert definition["format"] == "PBIR"
    paths = {p["path"] for p in definition["parts"]}
    assert "definition.pbir" in paths
    assert "definition/report.json" in paths

    out = tmp_path / "Out.Report"
    unpack_definition(definition, out)
    assert (out / "definition" / "report.json").is_file()


def test_parse_and_rewrite_pbir(tmp_path: Path) -> None:
    folder = _write_report(
        tmp_path / "Sales.Report",
        pbir=_pbir_by_path("../Sales.SemanticModel"),
    )
    ref = parse_dataset_reference(load_pbir(folder))
    assert ref.kind == "byPath"
    assert ref.by_path == "../Sales.SemanticModel"

    rewritten = rewrite_pbir_to_by_connection(
        load_pbir(folder), "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    bound = parse_dataset_reference(rewritten)
    assert bound.kind == "byConnection"
    assert bound.semantic_model_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def test_resolve_local_join_by_path(tmp_path: Path) -> None:
    model = _write_semantic_model(tmp_path / "Sales.SemanticModel")
    report = _write_report(
        tmp_path / "Sales.Report",
        pbir=_pbir_by_path("../Sales.SemanticModel"),
    )
    join = resolve_local_join(report)
    assert join.model_path == model.resolve()
    assert join.reference.kind == "byPath"


def test_resolve_local_join_sibling_stem(tmp_path: Path) -> None:
    model = _write_semantic_model(tmp_path / "Sales.SemanticModel")
    report = _write_report(
        tmp_path / "Sales.Report",
        pbir=_pbir_by_connection("cccccccc-cccc-cccc-cccc-cccccccccccc"),
    )
    join = resolve_local_join(report)
    assert join.model_path == model.resolve()
    assert join.reference.kind == "byConnection"


def test_by_path_missing_model_errors(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path / "Sales.Report",
        pbir=_pbir_by_path("../Missing.SemanticModel"),
    )
    with pytest.raises(DefinitionError, match="byPath"):
        resolve_local_join(report)


def test_rejects_both_formats(tmp_path: Path) -> None:
    folder = _write_report(tmp_path / "Sales.Report")
    (folder / "report.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DefinitionError, match="both"):
        validate_local_report(folder)


def test_pack_with_pbir_override(tmp_path: Path) -> None:
    folder = _write_report(
        tmp_path / "Sales.Report",
        pbir=_pbir_by_path("../Sales.SemanticModel"),
    )
    override = rewrite_pbir_to_by_connection(
        load_pbir(folder), "dddddddd-dddd-dddd-dddd-dddddddddddd"
    )
    definition = pack_definition(folder, pbir_override=override)
    from fabric_tools.report.definition import part_payloads

    payloads = part_payloads(definition)
    ref = parse_dataset_reference(
        json.loads(payloads["definition.pbir"].decode("utf-8"))
    )
    assert ref.semantic_model_id == "dddddddd-dddd-dddd-dddd-dddddddddddd"
