# AGENTS.md

Guidance for AI agents and contributors working on this repository.

Human contributor setup (install, pytest, exe build) is in [DEVELOPMENT.md](DEVELOPMENT.md). End-user CLI docs are in [README.md](README.md).

## Project goal

`fabric-tools` is a Python CLI (later optionally TUI / Windows `.exe`) for Microsoft Fabric. Phase 1: notebook download/deploy/compare sync.

## Layout

- `src/fabric_tools/` — package root
  - `cli.py` — Typer entrypoint (`fabric-tools`), aliases, help text, `inspect`
  - `interactive.py` — `--interactive` / `-i` guided wizard (optional `.ftdep` save)
  - `manifest.py` — deployment manifest (`.ftdep`) load/save/inspect helpers
  - `path_setup.py` — Windows user PATH install/uninstall (`fabric-tools path …`)
  - `auth.py` — Azure / Fabric token acquisition (SP env, WAM broker, browser/device code; persistent cache)
  - `client.py` — Fabric REST client + LRO polling (`get_workspace`, `get_item`)
  - `parsing.py` — `--target` / `--file` / `--origin` parsing and mode validation
  - `validate.py` — `--dry-run` remote/local checks
  - `confirm.py` — overwrite / create prompts
  - `status.py` — Rich spinner / status line for auth and long-running work
  - `exit_codes.py` — CLI exit code constants
  - `notebook/` — definition pack/unpack (`definition.py`); selective cell merge (`cells.py`); download/create/overwrite (`ops.py`); compare (`compare.py`, nbdime)
- `tests/` — unit tests
- `packaging/fabric-tools.spec` — PyInstaller one-file Windows build
- `scripts/build_exe.ps1` — build helper for `dist/fabric-tools.exe`

## Conventions

- Python 3.11+, `src/` layout, Hatchling build
- CLI framework: Typer; HTTP: httpx; auth: azure-identity (+ azure-identity-broker on Windows WAM)
- Prefer small, focused modules over large catch-all files
- Do not commit secrets, `.env`, or built `dist/` / `build/` artifacts
- Plan execution: complete one plan step, stop for user review/commit, wait for `continue`

## Phase 1 CLI contract (target)

- Targets: `--target <workspaceId>:<artifactId>` (create: `--target <workspaceId>` only)
- Files: `--file` paired 1:1 with targets, or one file broadcast to N targets (deploy/download)
- Origins: `--origin` / `-o` `<workspaceId>:<artifactId>` as Fabric source for deploy/compare (mutually exclusive with `--file`; deploy may broadcast one origin to N targets; compare is 1:1)
- Manifests: `--manifest` / `-m` stem → `.ftdep`; alone loads pairs; on success or successful dry-run rewrites (create execute backfills `itemId`). Schema v1 = file sources; v2 adds origin fields. Top-level `inspect` lists `.ftdep` in cwd; `inspect -m` shows one. Interactive may offer save after execute or dry-run.
- Formats: `.ipynb` or Fabric Git `.Notebook` folder
- Flags: `--silent`, `--dry-run`; deploy overwrite may use `--cells` / `-c` (1-based indices, single local `.ipynb` only)
- Auth: interactive default; service principal via `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET`
- Full `.ipynb` overwrite: fetch remote definition and merge omitted `metadata.dependencies` (`lakehouse`, `environment`) from remote before `updateDefinition`
- Origin overwrite: strip origin `lakehouse`/`environment`, then preserve each target’s dependency metadata

## Commands agents should know

See [DEVELOPMENT.md](DEVELOPMENT.md) for full install/test/build steps.

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m fabric_tools --version
py -3 -m pytest
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

Prefer `py -3` on this machine when the default `python` is not 3.11+.

Do not commit `dist/` or `build/`. Keep `packaging/fabric-tools.spec` checked in.
