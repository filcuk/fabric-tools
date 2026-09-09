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

- `.[dev]` — pytest and test helpers
- `.[build]` — PyInstaller for Windows executable builds

## Run from Python

```bash
py -3 -m fabric_tools --version
py -3 -m fabric_tools --help
py -3 -m fabric_tools notebook --help
py -3 -m fabric_tools --interactive
```

If Scripts is on your PATH after install, `fabric-tools` works the same way.

Examples match the user docs in [README.md](README.md); swap `.\fabric-tools.exe` for `py -3 -m fabric_tools` (or `fabric-tools`) while developing.

To register the current Python-based CLI on your user PATH (creates a `.cmd` shim under `%LOCALAPPDATA%\fabric-tools\bin`):

```bash
py -3 -m fabric_tools path install
```

## Tests

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m pytest
```

Covered areas: parsing/pairing, definition pack/unpack, LRO client (mocked HTTP), download/deploy ops, compare diffs, dry-run validation, interactive wizard dispatch.

## Build Windows executable

Produces a standalone one-file console app at `dist/fabric-tools.exe`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

Or manually:

```bash
py -3 -m pip install -e ".[build]"
py -3 -m PyInstaller --noconfirm --clean packaging/fabric-tools.spec
.\dist\fabric-tools.exe --help
```

Notes:

- Spec file: [`packaging/fabric-tools.spec`](packaging/fabric-tools.spec) (kept in git via `!packaging/*.spec`)
- Do not commit `dist/` or `build/`
- Unsigned binaries may trigger SmartScreen warnings
- Auth from the exe uses Windows WAM (when available), browser/device-code, or `AZURE_*` service principal env vars; tokens persist under `%LOCALAPPDATA%\fabric-tools`
