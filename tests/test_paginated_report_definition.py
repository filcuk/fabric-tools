"""Tests for paginated-report RDL helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from fabric_tools.paginated_report.definition import (
    DefinitionError,
    display_name_from_path,
    display_name_from_report,
    ensure_paginated_report,
    load_rdl,
    normalize_rdl_for_compare,
    rdl_to_diff_text,
    validate_local_rdl,
    write_rdl,
)

SAMPLE_RDL = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/'
    b'2016/01/reportdefinition">\n'
    b"  <Width>6.5in</Width>\n"
    b"</Report>\n"
)


def test_load_and_validate_rdl(tmp_path: Path) -> None:
    path = tmp_path / "Sales.rdl"
    write_rdl(SAMPLE_RDL, path)
    loaded = load_rdl(path)
    assert loaded.startswith(b"<?xml")
    assert validate_local_rdl(path) == path
    assert display_name_from_path(path) == "Sales"


def test_load_rdl_rejects_non_report_root(tmp_path: Path) -> None:
    path = tmp_path / "bad.rdl"
    path.write_text("<NotReport />", encoding="utf-8")
    with pytest.raises(DefinitionError, match="Report"):
        load_rdl(path)


def test_load_rdl_rejects_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.rdl"
    path.write_bytes(b"")
    with pytest.raises(DefinitionError, match="empty"):
        load_rdl(path)


def test_normalize_ignores_bom_and_crlf() -> None:
    crlf = b"\xef\xbb\xbf" + SAMPLE_RDL.replace(b"\n", b"\r\n")
    assert normalize_rdl_for_compare(crlf) == rdl_to_diff_text(SAMPLE_RDL)


def test_ensure_paginated_report() -> None:
    meta = {"id": "r1", "name": "Sales", "reportType": "PaginatedReport"}
    assert display_name_from_report(ensure_paginated_report(meta)) == "Sales"
    with pytest.raises(DefinitionError, match="PaginatedReport"):
        ensure_paginated_report({"reportType": "PowerBIReport"}, label="x")
