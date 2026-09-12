"""Tests for Nuitka packaging option helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PACKAGING = _PROJECT_ROOT / "packaging"
if str(_PACKAGING) not in sys.path:
    sys.path.insert(0, str(_PACKAGING))

from nuitka_options import (  # noqa: E402
    EXE_NAME,
    entry_script,
    nuitka_command,
    shared_nuitka_args,
)


@pytest.fixture
def project_root() -> Path:
    return _PROJECT_ROOT


def test_entry_script_exists(project_root: Path) -> None:
    assert entry_script(project_root).is_file()


def test_shared_nuitka_args_include_core_flags(project_root: Path) -> None:
    args = shared_nuitka_args(project_root)
    assert f"--output-filename={EXE_NAME}" in args
    assert "--mingw64" in args
    assert "--assume-yes-for-downloads" in args
    assert "--include-package=fabric_tools" in args
    assert "--include-package=azure.identity" in args
    assert "--include-package-data=certifi" in args
    assert "--nofollow-import-to=*.tests" in args
    icon = project_root / "res" / "app.ico"
    if icon.is_file():
        assert f"--windows-icon-from-ico={icon}" in args


def test_nuitka_command_standalone_and_onefile(
    project_root: Path, tmp_path: Path
) -> None:
    out = (tmp_path / "out").resolve()
    standalone = nuitka_command(project_root, mode="standalone", output_dir=out)
    assert standalone[:4] == [
        "-m",
        "nuitka",
        "--mode=standalone",
        f"--output-dir={out}",
    ]
    assert standalone[-1] == str(entry_script(project_root))

    onefile = nuitka_command(project_root, mode="onefile", output_dir=out)
    assert "--mode=onefile" in onefile


def test_nuitka_command_rejects_unknown_mode(
    project_root: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="unsupported Nuitka mode"):
        nuitka_command(project_root, mode="accelerated", output_dir=tmp_path)
