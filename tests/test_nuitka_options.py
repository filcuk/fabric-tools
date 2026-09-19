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
    compiler_args,
    entry_script,
    nuitka_command,
    shared_nuitka_args,
    windows_file_version,
)


@pytest.fixture
def project_root() -> Path:
    return _PROJECT_ROOT


def test_entry_script_exists(project_root: Path) -> None:
    assert entry_script(project_root).is_file()


def test_compiler_args_by_python_version() -> None:
    assert compiler_args(version_info=(3, 12)) == ["--mingw64"]
    assert compiler_args(version_info=(3, 13)) == ["--msvc=latest"]
    assert compiler_args(version_info=(3, 14)) == ["--msvc=latest"]


def test_windows_file_version_normalization() -> None:
    assert windows_file_version("0.3.0") == "0.3.0.0"
    assert windows_file_version("1.2.3.4") == "1.2.3.4"
    assert windows_file_version("0.3.0-dev") == "0.3.0.0"


def test_shared_nuitka_args_include_core_flags(project_root: Path) -> None:
    args = shared_nuitka_args(project_root, version_info=(3, 12))
    assert f"--output-filename={EXE_NAME}" in args
    assert "--mingw64" in args
    assert "--msvc=latest" not in args
    assert "--assume-yes-for-downloads" in args
    assert "--no-deployment-flag=self-execution" in args
    win_version = windows_file_version()
    assert f"--file-version={win_version}" in args
    assert f"--product-version={win_version}" in args
    assert "--include-package=fabric_tools" in args
    assert "--output-folder-name=fabric-tools" in args
    assert "--onefile-tempdir-spec={CACHE_DIR}/{COMPANY}/cache/{VERSION}" in args
    assert "--include-package=azure.identity" in args
    assert "--include-package-data=certifi" in args
    assert "--nofollow-import-to=*.tests" in args
    xmla_script = project_root / "src" / "fabric_tools" / "xmla_role_members.ps1"
    if xmla_script.is_file():
        assert (
            f"--include-data-files={xmla_script}=fabric_tools/xmla_role_members.ps1"
            in args
        )
    icon = project_root / "res" / "app.ico"
    if icon.is_file():
        assert f"--windows-icon-from-ico={icon}" in args

    msvc_args = shared_nuitka_args(project_root, version_info=(3, 14))
    assert "--msvc=latest" in msvc_args
    assert "--mingw64" not in msvc_args


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
