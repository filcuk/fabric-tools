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
    def __init__(self, *, remote_cells: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.remote_cells = remote_cells if remote_cells is not None else []
        self.create_response = {
            "id": "99999999-9999-9999-9999-999999999999",
            "type": "Notebook",
            "displayName": "Demo",
            "workspaceId": "11111111-1111-1111-1111-111111111111",
        }
        self.last_update_definition: dict[str, Any] | None = None

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
                        "cells": self.remote_cells,
                        "metadata": {"remote": True},
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
            self.last_update_definition = json
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


def test_upload_selective_cells(tmp_path: Path) -> None:
    remote_cells = [
        {"cell_type": "code", "metadata": {}, "source": ["r1\n"], "outputs": []},
        {"cell_type": "code", "metadata": {}, "source": ["r2\n"], "outputs": []},
        {"cell_type": "code", "metadata": {}, "source": ["r3\n"], "outputs": []},
    ]
    client = FakeClient(remote_cells=remote_cells)
    src = tmp_path / "demo.ipynb"
    local = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"local": True},
        "cells": [
            {
                "cell_type": "code",
                "metadata": {},
                "source": ["l1\n"],
                "outputs": [{"output_type": "stream", "text": ["hi\n"]}],
            },
            {"cell_type": "code", "metadata": {}, "source": ["l2\n"], "outputs": []},
            {"cell_type": "code", "metadata": {}, "source": ["l3\n"], "outputs": []},
        ],
    }
    src.write_text(json.dumps(local), encoding="utf-8")
    item = WorkItem(
        Target("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"),
        src,
    )
    result = upload_notebook(client, item, cell_indices=[1, 3])  # type: ignore[arg-type]
    assert result.ok
    assert "cells [1, 3]" in result.message
    assert any(call[1].endswith("/getDefinition") for call in client.calls)
    assert client.last_update_definition is not None
    parts = client.last_update_definition["definition"]["parts"]
    payload = base64.b64decode(parts[0]["payload"])
    merged = json.loads(payload.decode("utf-8"))
    assert merged["metadata"] == {"remote": True}
    assert merged["cells"][0]["source"] == ["l1\n"]
    assert merged["cells"][0]["outputs"] == [{"output_type": "stream", "text": ["hi\n"]}]
    assert merged["cells"][1]["source"] == ["r2\n"]
    assert merged["cells"][2]["source"] == ["l3\n"]


def test_upload_selective_cells_missing_remote(tmp_path: Path) -> None:
    client = FakeClient(
        remote_cells=[
            {"cell_type": "code", "metadata": {}, "source": ["r1\n"], "outputs": []},
        ]
    )
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [
                    {"cell_type": "code", "metadata": {}, "source": ["l1\n"], "outputs": []},
                    {"cell_type": "code", "metadata": {}, "source": ["l2\n"], "outputs": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    item = WorkItem(
        Target("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"),
        src,
    )
    result = upload_notebook(client, item, cell_indices=[1, 2])  # type: ignore[arg-type]
    assert not result.ok
    assert "missing index" in result.message
