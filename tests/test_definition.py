"""Tests for notebook definition pack/unpack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabric_tools.notebook.definition import (
    DefinitionError,
    NotebookFormat,
    definition_has_platform,
    display_name_from_path,
    merge_remote_dependencies,
    normalize_ipynb,
    pack_definition,
    read_ipynb,
    unpack_definition,
    validate_local_notebook,
)


def test_pack_unpack_ipynb(tmp_path: Path) -> None:
    src = tmp_path / "demo.ipynb"
    src.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "cells": [],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    assert validate_local_notebook(src) is NotebookFormat.IPYNB
    definition = pack_definition(src)
    assert definition["format"] == "ipynb"
    assert len(definition["parts"]) == 1

    out = tmp_path / "out.ipynb"
    unpack_definition(definition, out)
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8"))["nbformat"] == 4


def test_pack_unpack_fabric_git(tmp_path: Path) -> None:
    folder = tmp_path / "MyNote.Notebook"
    folder.mkdir()
    (folder / "notebook-content.py").write_text("# hello\n", encoding="utf-8")
    (folder / ".platform").write_text('{"version":"2.0"}', encoding="utf-8")

    assert display_name_from_path(folder) == "MyNote"
    definition = pack_definition(folder)
    assert definition["format"] == "fabricGitSource"
    assert definition_has_platform(definition)

    out = tmp_path / "Restored.Notebook"
    unpack_definition(definition, out)
    assert (out / "notebook-content.py").read_text(encoding="utf-8") == "# hello\n"
    assert (out / ".platform").is_file()


def test_fabric_git_missing_platform(tmp_path: Path) -> None:
    folder = tmp_path / "Bad.Notebook"
    folder.mkdir()
    (folder / "notebook-content.py").write_text("x=1\n", encoding="utf-8")
    with pytest.raises(DefinitionError, match="\\.platform"):
        validate_local_notebook(folder)


def test_rejects_unsupported_path(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(DefinitionError, match="Unsupported"):
        validate_local_notebook(path)


def test_merge_remote_dependencies_fills_omitted_keys() -> None:
    local = {"nbformat": 4, "cells": [], "metadata": {"kernelspec": {"name": "python3"}}}
    remote = {
        "nbformat": 4,
        "cells": [],
        "metadata": {
            "dependencies": {
                "lakehouse": {
                    "default_lakehouse": "lh-id",
                    "default_lakehouse_name": "LH",
                    "default_lakehouse_workspace_id": "ws-id",
                    "known_lakehouses": [{"id": "lh-id"}],
                },
                "environment": {"environmentId": "env-id", "workspaceId": "ws-id"},
            }
        },
    }
    merged, preserved = merge_remote_dependencies(local, remote)
    assert preserved == ["lakehouse", "environment"]
    assert merged["metadata"]["kernelspec"]["name"] == "python3"
    assert merged["metadata"]["dependencies"]["lakehouse"]["default_lakehouse"] == "lh-id"
    assert merged["metadata"]["dependencies"]["environment"]["environmentId"] == "env-id"
    # Local input unchanged.
    assert "dependencies" not in local["metadata"]


def test_merge_remote_dependencies_keeps_explicit_local() -> None:
    local = {
        "nbformat": 4,
        "cells": [],
        "metadata": {"dependencies": {"lakehouse": {}, "environment": {"environmentId": "local"}}},
    }
    remote = {
        "nbformat": 4,
        "cells": [],
        "metadata": {
            "dependencies": {
                "lakehouse": {"default_lakehouse": "lh-id"},
                "environment": {"environmentId": "remote"},
            }
        },
    }
    merged, preserved = merge_remote_dependencies(local, remote)
    assert preserved == []
    assert merged["metadata"]["dependencies"]["lakehouse"] == {}
    assert merged["metadata"]["dependencies"]["environment"]["environmentId"] == "local"


def test_merge_remote_dependencies_noop_without_remote() -> None:
    local = {"nbformat": 4, "cells": [], "metadata": {}}
    merged, preserved = merge_remote_dependencies(local, {"nbformat": 4, "cells": [], "metadata": {}})
    assert preserved == []
    assert merged == local


def test_normalize_ipynb_adds_missing_cell_ids() -> None:
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {
                "cell_type": "code",
                "source": ["print(1)\n"],
                "metadata": {},
                "outputs": [],
                "execution_count": None,
            }
        ],
    }
    assert "id" not in notebook["cells"][0]
    normalized = normalize_ipynb(notebook)
    assert "id" in normalized["cells"][0]
    assert isinstance(normalized["cells"][0]["id"], str)
    assert normalized["cells"][0]["id"]


def test_read_ipynb_normalizes_cell_ids(tmp_path: Path) -> None:
    path = tmp_path / "noid.ipynb"
    path.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [
                    {
                        "cell_type": "markdown",
                        "source": ["# hi\n"],
                        "metadata": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = read_ipynb(path)
    assert loaded["cells"][0]["id"]
