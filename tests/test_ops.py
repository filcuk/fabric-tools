"""Tests for notebook download/deploy ops with a fake Fabric client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.notebook.compare import compare_notebook
from fabric_tools.notebook.definition import IPYNB_PART_PATH, PAYLOAD_TYPE
from fabric_tools.notebook.ops import deploy_notebook, download_notebook
from fabric_tools.parsing import Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
ORIGIN_ITEM = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TARGET_ITEM = "22222222-2222-2222-2222-222222222222"
WS2 = "44444444-4444-4444-4444-444444444444"


class FakeClient:
    def __init__(
        self,
        *,
        remote_cells: list[dict[str, Any]] | None = None,
        remote_metadata: dict[str, Any] | None = None,
        definitions_by_item: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.remote_cells = remote_cells if remote_cells is not None else []
        self.remote_metadata = (
            remote_metadata if remote_metadata is not None else {"remote": True}
        )
        self.definitions_by_item = definitions_by_item or {}
        self.create_response = {
            "id": "99999999-9999-9999-9999-999999999999",
            "type": "Notebook",
            "displayName": "Demo",
            "workspaceId": WS,
        }
        self.last_update_definition: dict[str, Any] | None = None

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "WS"}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": "Origin NB",
            "type": "Notebook",
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
            item_id = path.split("/")[-2]
            if item_id in self.definitions_by_item:
                nb = self.definitions_by_item[item_id]
            else:
                nb = {
                    "nbformat": 4,
                    "nbformat_minor": 5,
                    "cells": self.remote_cells,
                    "metadata": self.remote_metadata,
                }
            payload = base64.b64encode(json_module_dumps(nb).encode("utf-8")).decode(
                "ascii"
            )
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
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        dest,
    )
    result = download_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert dest.is_file()
    assert any(call[1].endswith("/getDefinition") for call in client.calls)


def test_deploy_create(tmp_path: Path) -> None:
    client = FakeClient()
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps({"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}),
        encoding="utf-8",
    )
    item = WorkItem(Target("11111111-1111-1111-1111-111111111111"), src)
    result = deploy_notebook(client, item, display_name="Demo")  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == "99999999-9999-9999-9999-999999999999"
    assert any(call[1].endswith("/items") for call in client.calls)


def test_delete_notebook() -> None:
    from fabric_tools.notebook.ops import delete_notebook

    client = FakeClient()

    def request(
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        client.calls.append((method, path, params, json))
        if method == "DELETE" and "/notebooks/" in path:
            return None
        raise AssertionError(f"Unexpected call {method} {path}")

    client.request = request  # type: ignore[method-assign]
    item = WorkItem(Target(WS, TARGET_ITEM), None)
    result = delete_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.calls[0][0] == "DELETE"


def test_deploy_overwrite(tmp_path: Path) -> None:
    client = FakeClient()
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps({"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}),
        encoding="utf-8",
    )
    item = WorkItem(
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        src,
    )
    result = deploy_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert any(call[1].endswith("/getDefinition") for call in client.calls)
    assert any(call[1].endswith("/updateDefinition") for call in client.calls)


def test_deploy_overwrite_preserves_remote_lakehouse(tmp_path: Path) -> None:
    remote_meta = {
        "dependencies": {
            "lakehouse": {
                "default_lakehouse": "lh-id",
                "default_lakehouse_name": "LH",
                "default_lakehouse_workspace_id": "ws-id",
            }
        }
    }
    client = FakeClient(remote_metadata=remote_meta)
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps({"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}),
        encoding="utf-8",
    )
    item = WorkItem(
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        src,
    )
    result = deploy_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "preserved remote lakehouse" in result.message
    assert client.last_update_definition is not None
    parts = client.last_update_definition["definition"]["parts"]
    payload = base64.b64decode(parts[0]["payload"])
    uploaded = json.loads(payload.decode("utf-8"))
    assert (
        uploaded["metadata"]["dependencies"]["lakehouse"]["default_lakehouse"]
        == "lh-id"
    )


def test_deploy_overwrite_keeps_explicit_local_lakehouse(tmp_path: Path) -> None:
    client = FakeClient(
        remote_metadata={
            "dependencies": {"lakehouse": {"default_lakehouse": "remote-lh"}}
        }
    )
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "cells": [],
                "metadata": {"dependencies": {"lakehouse": {}}},
            }
        ),
        encoding="utf-8",
    )
    item = WorkItem(
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        src,
    )
    result = deploy_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "preserved remote" not in result.message
    assert client.last_update_definition is not None
    parts = client.last_update_definition["definition"]["parts"]
    payload = base64.b64decode(parts[0]["payload"])
    uploaded = json.loads(payload.decode("utf-8"))
    assert uploaded["metadata"]["dependencies"]["lakehouse"] == {}


def test_deploy_selective_cells(tmp_path: Path) -> None:
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
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        src,
    )
    result = deploy_notebook(client, item, cell_indices=[1, 3])  # type: ignore[arg-type]
    assert result.ok
    assert "cells [1, 3]" in result.message
    assert any(call[1].endswith("/getDefinition") for call in client.calls)
    assert client.last_update_definition is not None
    parts = client.last_update_definition["definition"]["parts"]
    payload = base64.b64decode(parts[0]["payload"])
    merged = json.loads(payload.decode("utf-8"))
    assert merged["metadata"] == {"remote": True}
    assert merged["cells"][0]["source"] == ["l1\n"]
    assert merged["cells"][0]["outputs"] == [
        {"output_type": "stream", "text": ["hi\n"]}
    ]
    assert merged["cells"][1]["source"] == ["r2\n"]
    assert merged["cells"][2]["source"] == ["l3\n"]


def test_deploy_selective_cells_missing_remote(tmp_path: Path) -> None:
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
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": ["l1\n"],
                        "outputs": [],
                    },
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": ["l2\n"],
                        "outputs": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    item = WorkItem(
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        src,
    )
    result = deploy_notebook(client, item, cell_indices=[1, 2])  # type: ignore[arg-type]
    assert not result.ok
    assert "missing index" in result.message


def test_deploy_from_origin_preserves_target_lakehouse() -> None:
    origin_nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": ["origin\n"], "outputs": []}
        ],
        "metadata": {
            "dependencies": {
                "lakehouse": {"default_lakehouse": "dev-lh"},
                "environment": {"environmentId": "dev-env"},
            }
        },
    }
    target_nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [],
        "metadata": {
            "dependencies": {
                "lakehouse": {"default_lakehouse": "test-lh"},
                "environment": {"environmentId": "test-env"},
            }
        },
    }
    client = FakeClient(
        definitions_by_item={
            ORIGIN_ITEM: origin_nb,
            TARGET_ITEM: target_nb,
        }
    )
    item = WorkItem(
        Target(WS2, TARGET_ITEM),
        None,
        origin=Target(WS, ORIGIN_ITEM),
    )
    result = deploy_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "preserved remote lakehouse, environment" in result.message
    assert client.last_update_definition is not None
    parts = client.last_update_definition["definition"]["parts"]
    payload = base64.b64decode(parts[0]["payload"])
    uploaded = json.loads(payload.decode("utf-8"))
    assert uploaded["cells"][0]["source"] == ["origin\n"]
    assert (
        uploaded["metadata"]["dependencies"]["lakehouse"]["default_lakehouse"]
        == "test-lh"
    )
    assert (
        uploaded["metadata"]["dependencies"]["environment"]["environmentId"]
        == "test-env"
    )


def test_deploy_create_from_origin_uses_display_name() -> None:
    client = FakeClient(
        definitions_by_item={
            ORIGIN_ITEM: {
                "nbformat": 4,
                "nbformat_minor": 5,
                "cells": [],
                "metadata": {},
            }
        }
    )
    item = WorkItem(Target(WS2), None, origin=Target(WS, ORIGIN_ITEM))
    result = deploy_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "Origin NB" in result.message
    create_calls = [c for c in client.calls if c[1].endswith("/items")]
    assert create_calls
    assert create_calls[0][3]["displayName"] == "Origin NB"


def test_compare_origin_to_target_identical() -> None:
    shared = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": ["same\n"], "outputs": []}
        ],
        "metadata": {},
    }
    client = FakeClient(definitions_by_item={ORIGIN_ITEM: shared, TARGET_ITEM: shared})
    item = WorkItem(
        Target(WS2, TARGET_ITEM),
        None,
        origin=Target(WS, ORIGIN_ITEM),
    )
    result = compare_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.identical
    assert "origin" in result.header
    assert "target" in result.header


def test_compare_origin_to_target_differs() -> None:
    origin_nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": ["dev\n"], "outputs": []}
        ],
        "metadata": {},
    }
    target_nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": ["test\n"], "outputs": []}
        ],
        "metadata": {},
    }
    client = FakeClient(
        definitions_by_item={ORIGIN_ITEM: origin_nb, TARGET_ITEM: target_nb}
    )
    item = WorkItem(
        Target(WS2, TARGET_ITEM),
        None,
        origin=Target(WS, ORIGIN_ITEM),
    )
    result = compare_notebook(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert result.diff_text


def test_deploy_create_applies_guid_map(tmp_path: Path) -> None:
    lh_src = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    lh_dst = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "cells": [
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": [f'lakehouse = "{lh_src}"\n'],
                        "outputs": [],
                    }
                ],
                "metadata": {
                    "dependencies": {
                        "lakehouse": {
                            "default_lakehouse": lh_src,
                            "default_lakehouse_workspace_id": WS,
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    client = FakeClient()
    item = WorkItem(Target(WS), src)
    result = deploy_notebook(
        client, item, display_name="Demo", guid_map={lh_src: lh_dst}
    )  # type: ignore[arg-type]
    assert result.ok
    assert "remapped 2 GUID(s)" in result.message
    create = next(
        c for c in client.calls if c[0] == "POST" and str(c[1]).endswith("/items")
    )
    payload = create[3]["definition"]["parts"][0]["payload"]
    nb = json.loads(base64.b64decode(payload).decode("utf-8"))
    assert nb["metadata"]["dependencies"]["lakehouse"]["default_lakehouse"] == lh_dst
    assert lh_dst in "".join(nb["cells"][0]["source"])
    local = json.loads(src.read_text(encoding="utf-8"))
    assert local["metadata"]["dependencies"]["lakehouse"]["default_lakehouse"] == lh_src
