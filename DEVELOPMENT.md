# Development

Contributor guide for `fabric-tools`. End-user CLI usage lives in [README.md](README.md). Agent-oriented project notes live in [AGENTS.md](AGENTS.md).

## Requirements

- Python 3.11+ (`py -3` on Windows if `python` points at an older runtime)
- Access to a Microsoft Fabric tenant (for live API operations)

## Install

From the repo root:

```bash
py -3 -m pip install -e ".[dev]"
```

Optional extras:

- `.[dev]` — pytest, Ruff, and test helpers
- `.[build]` — PyInstaller for Windows executable builds

## Run from Python

```bash
py -3 -m fabric_tools --version
py -3 -m fabric_tools --help
py -3 -m fabric_tools notebook --help
py -3 -m fabric_tools udf --help
py -3 -m fabric_tools --interactive
```

If Scripts is on your PATH after install, `fabric-tools` works the same way.

Examples match the user docs in [README.md](README.md); swap `.\fabric-tools.exe` for `py -3 -m fabric_tools` (or `fabric-tools`) while developing.

To register the current Python-based CLI for your user account (creates a `.cmd` shim under `%LOCALAPPDATA%\fabric-tools\app`):

```bash
py -3 -m fabric_tools setup install
```

## Lint and format

Uses [Ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`):

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m ruff check .
py -3 -m ruff format --check .
```

To apply fixes and reformat:

```bash
py -3 -m ruff check --fix .
py -3 -m ruff format .
```

## Tests

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m pytest
```

Covered areas: parsing/pairing, definition pack/unpack, LRO client (mocked HTTP), download/deploy ops, compare diffs, dry-run validation, interactive wizard dispatch.

## Build Windows executable

Produces a single portable `dist/fabric-tools.exe` (one-file). `setup install` unpacks it to a fast onedir tree under `%LOCALAPPDATA%\fabric-tools\app`.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

The script builds onedir staging first, then a onefile release that embeds the thin onedir bootloader. Or manually:

```bash
py -3 -m pip install -e ".[build]"
py -3 -m PyInstaller --noconfirm --clean packaging/fabric-tools.spec
set FABRIC_TOOLS_ONEDIR_BOOTLOADER=%CD%\dist\fabric-tools\fabric-tools.exe
py -3 -m PyInstaller --noconfirm --clean packaging/fabric-tools-onefile.spec
.\dist\fabric-tools.exe --help
```

Notes:

- Spec files: [`packaging/fabric-tools.spec`](packaging/fabric-tools.spec) (onedir staging), [`packaging/fabric-tools-onefile.spec`](packaging/fabric-tools-onefile.spec) (release); shared inputs in [`packaging/analysis_inputs.py`](packaging/analysis_inputs.py)
- Ship the single `dist/fabric-tools.exe`. Portable runs unpack to temp each launch (slower); `setup install` copies to an onedir install for fast PATH use
- Do not commit `dist/` or `build/`
- Unsigned binaries may trigger SmartScreen warnings
- Auth from the exe uses Windows WAM (when available), browser/device-code, or `AZURE_*` service principal env vars; tokens persist under `%LOCALAPPDATA%\fabric-tools`
