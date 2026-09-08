"""Tests for notebook download/upload ops with a fake Fabric client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.notebook.definition import IPYNB_PART_PATH, PAYLOAD_TYPE
from fabric_tools.notebook.ops import download_notebook, upload_notebook
from fabric_tools.parsing import Target, WorkItem


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.create_response = {
            "id": "99999999-9999-9999-9999-999999999999",
            "type": "Notebook",
            "displayName": "Demo",
            "workspaceId": "11111111-1111-1111-1111-111111111111",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        self.calls.append((method, path, params, json))
        if method == "POST" and path.endswith("/getDefinition"):
            payload = base64.b64encode(
                json_module_dumps(
                    {
                        "nbformat": 4,
                        "nbformat_minor": 5,
                        "cells": [],
                        "metadata": {},
                    }
                ).encode("utf-8")
            ).decode("ascii")
            return {
                "definition": {
                    "format": "ipynb",
                    "parts": [
                        {
                            "path": IPYNB_PART_PATH,
                            "payload": payload,
                            "payloadType": PAYLOAD_TYPE,
                        }
                    ],
                }
            }
        if method == "POST" and path.endswith("/items"):
            return self.create_response
        if method == "POST" and path.endswith("/updateDefinition"):
            return None
        raise AssertionError(f"Unexpected call {method} {path}")


def json_module_dumps(obj: Any) -> str:
    return json.dumps(obj)


def test_download_writes_ipynb(tmp_path: Path) -> None:
    client = FakeClient()
    dest = tmp_path / "out.ipynb"
    item = WorkItem(
        Target("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"),
        dest,
    )
    result = download_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert dest.is_file()
    assert any(call[1].endswith("/getDefinition") for call in client.calls)


def test_upload_create(tmp_path: Path) -> None:
    client = FakeClient()
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps(
            {"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}
        ),
        encoding="utf-8",
    )
    item = WorkItem(Target("11111111-1111-1111-1111-111111111111"), src)
    result = upload_notebook(client, item, display_name="Demo")  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == "99999999-9999-9999-9999-999999999999"
    assert any(call[1].endswith("/items") for call in client.calls)


def test_upload_overwrite(tmp_path: Path) -> None:
    client = FakeClient()
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps(
            {"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}
        ),
        encoding="utf-8",
    )
    item = WorkItem(
        Target("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"),
        src,
    )
    result = upload_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert any(call[1].endswith("/updateDefinition") for call in client.calls)
