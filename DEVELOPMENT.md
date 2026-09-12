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
- `.[build]` — Nuitka for Windows executable builds

## Run from Python

```bash
py -3 -m fabric_tools --version
py -3 -m fabric_tools --help
py -3 -m fabric_tools inspect --help
py -3 -m fabric_tools notebook --help
py -3 -m fabric_tools pipeline --help
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

Produces a single portable `dist/fabric-tools.exe` via **Nuitka onefile**. Prefer **Python 3.12** for the build (`py -3.12`); 3.13+ needs MSVC instead of MinGW.

`setup install` unpacks to a fast tree under `%LOCALAPPDATA%\fabric-tools\app`.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
.\dist\fabric-tools.exe --help
```

Notes:

- Packaging: [`packaging/nuitka_options.py`](packaging/nuitka_options.py), [`packaging/nuitka_entry.py`](packaging/nuitka_entry.py)
- Ship only `dist/fabric-tools.exe`. Do not distribute `dist/nuitka/` intermediates (`.dist` / `.build`)
- Portable runs extract on each launch; `setup install` is for everyday use
- Do not commit `dist/` or `build/`
- Unsigned binaries may trigger SmartScreen warnings
- Auth from the exe uses Windows WAM (when available), browser/device-code, or `AZURE_*` service principal env vars; tokens persist under `%LOCALAPPDATA%\fabric-tools`
