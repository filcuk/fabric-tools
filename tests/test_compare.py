"""Tests for local notebook compare helpers."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from nbformat.validator import MissingIDFieldWarning

from fabric_tools.notebook.compare import _diff_fabric_git, _diff_ipynb, _load_notebook_for_diff


def test_ipynb_diff_detects_change(tmp_path: Path) -> None:
    a = tmp_path / "a.ipynb"
    b = tmp_path / "b.ipynb"
    base = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {
                "cell_type": "code",
                "source": ["print(1)\n"],
                "metadata": {},
                "outputs": [],
                "execution_count": None,
            }
        ],
        "metadata": {},
    }
    a.write_text(json.dumps(base), encoding="utf-8")
    changed = json.loads(json.dumps(base))
    changed["cells"][0]["source"] = ["print(2)\n"]
    b.write_text(json.dumps(changed), encoding="utf-8")

    with warnings.catch_warnings():
        warnings.simplefilter("error", MissingIDFieldWarning)
        different = _diff_ipynb(
            "hdr",
            left_path=a,
            right_path=b,
            left_label="remote:a.ipynb",
            right_label="local:b.ipynb",
            ignore_outputs=True,
        )
    assert different.ok and not different.identical and different.diff_text

    same = _diff_ipynb(
        "hdr",
        left_path=a,
        right_path=a,
        left_label="remote:a.ipynb",
        right_label="local:a.ipynb",
        ignore_outputs=True,
    )
    assert same.ok and same.identical


def test_load_notebook_for_diff_no_missing_id_warning(tmp_path: Path) -> None:
    path = tmp_path / "noid.ipynb"
    path.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [
                    {
                        "cell_type": "code",
                        "source": ["x=1\n"],
                        "metadata": {},
                        "outputs": [],
                        "execution_count": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", MissingIDFieldWarning)
        notebook = _load_notebook_for_diff(path)
    assert "id" not in notebook.cells[0]


def test_fabric_git_text_diff(tmp_path: Path) -> None:
    remote = tmp_path / "remote.Notebook"
    local = tmp_path / "local.Notebook"
    remote.mkdir()
    local.mkdir()
    (remote / "notebook-content.py").write_text("x=1\n", encoding="utf-8")
    (local / "notebook-content.py").write_text("x=2\n", encoding="utf-8")
    (remote / ".platform").write_text("{}", encoding="utf-8")
    (local / ".platform").write_text("{}", encoding="utf-8")

    result = _diff_fabric_git("hdr", remote_dir=remote, local_dir=local)
    assert result.ok and not result.identical
    assert "x=1" in result.diff_text or "-x=1" in result.diff_text
