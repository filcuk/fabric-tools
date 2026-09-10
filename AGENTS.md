# AGENTS.md

Guidance for AI agents and contributors working on this repository.

Human contributor setup (install, pytest, ruff, exe build) is in [DEVELOPMENT.md](DEVELOPMENT.md). End-user CLI docs are in [README.md](README.md).

## Project goal

`fabric-tools` is a Python CLI (later optionally TUI / Windows `.exe`) for Microsoft Fabric artifacts. Current scope: notebook sync (download/deploy/compare/delete) and Dataflow Gen1 sync via Power BI (download/create-only deploy/compare/delete). Dataflow Gen2 is out of scope for now.

## Layout

- `src/fabric_tools/` — package root
  - `cli.py` — Typer entrypoint (`fabric-tools`), notebook + `dataflow-gen1` groups, `inspect`, `update`
  - `interactive.py` — `--interactive` / `-i` guided wizard (optional `.ftdep` save)
  - `manifest.py` — deployment manifest (`.ftdep`) load/save/inspect helpers (`kind`: `notebook` \| `dataflow-gen1`)
  - `path_setup.py` — Windows user install/uninstall (`fabric-tools setup …`; onefile unpacks to onedir under `%LOCALAPPDATA%\fabric-tools\app`)
  - `update_check.py` — GitHub Releases latest-version check (`fabric-tools update --check`)
  - `auth.py` — Azure token acquisition (Fabric + Power BI scopes; SP env, WAM broker, browser/device code; persistent cache)
  - `client.py` — Fabric REST client + LRO polling (`get_workspace`, `get_item`)
  - `powerbi_client.py` — Power BI REST client (Gen1 dataflow get/delete/import + poll)
  - `parsing.py` — `--target` / `--file` / `--origin` parsing and mode validation (`download` \| `deploy` \| `compare` \| `delete`; `deploy_create_only` for Gen1)
  - `validate.py` — `--dry-run` remote/local checks (Fabric notebooks + Power BI Gen1)
  - `confirm.py` — overwrite / create / delete prompts
  - `status.py` — Rich spinner / status line for auth and long-running work
  - `exit_codes.py` — CLI exit code constants
  - `notebook/` — definition pack/unpack (`definition.py`); selective cell merge (`cells.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`, nbdime)
  - `dataflow_gen1/` — `model.json` helpers (`definition.py`); download/create/delete (`ops.py`); compare (`compare.py`)
- `tests/` — unit tests
- `packaging/fabric-tools.spec` — PyInstaller onedir staging build
- `packaging/fabric-tools-onefile.spec` — PyInstaller one-file release (embeds onedir bootloader)
- `scripts/build_exe.ps1` — two-pass build → `dist/fabric-tools.exe`

## Conventions

- Python 3.11+, `src/` layout, Hatchling build
- CLI framework: Typer; HTTP: httpx; auth: azure-identity (+ azure-identity-broker on Windows WAM)
- Prefer small, focused modules over large catch-all files
- Lint/format with Ruff (`ruff check` / `ruff format`; config in `pyproject.toml`)
- Do not commit secrets, `.env`, or built `dist/` / `build/` artifacts
- Plan execution: complete one plan step, stop for user review/commit, wait for `continue`

## CLI contract

### Shared

- Targets: `--target <workspaceId>:<artifactId>` (create: `--target <workspaceId>` only). Repeatable or comma-separated. Overwrite CSV is one workspace per flag value (bare artifact GUIDs inherit that workspace; use separate `-t` for other workspaces). Create CSV may list multiple workspaces.
- Files: `--file` paired 1:1 with targets, or one file broadcast to N targets (deploy/download). Download may omit `--file` (defaults to remote display name + `.ipynb` / `.json` in the current folder).
- Origins: `--origin` / `-o` `<workspaceId>:<artifactId>` for deploy/compare (mutually exclusive with `--file`; same per-flag shorthand as targets; deploy may broadcast one origin to N targets; compare is 1:1)
- Delete: `--target` workspace:artifact only (no `--file`/`--origin`); optional `-m` load when entries have `itemId` (manifest not rewritten after delete)
- Manifests: `--manifest` / `-m` stem → `.ftdep`; alone loads pairs; on success or successful dry-run rewrites (create execute backfills `itemId`). Schema v1 = file sources; v2 adds origin fields. Top-level `inspect` lists `.ftdep` in cwd; `inspect -m` shows one. Interactive may offer save after execute or dry-run.
- Flags: `--silent`, `--dry-run`
- Auth: interactive default; service principal via `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET`

### Notebooks

- Formats: `.ipynb` or Fabric Git `.Notebook` folder
- Deploy: create or overwrite; overwrite may use `--cells` / `-c` (1-based, single local `.ipynb` only)
- Full `.ipynb` overwrite: merge omitted `metadata.dependencies` (`lakehouse`, `environment`) from remote before `updateDefinition`
- Origin overwrite: strip origin `lakehouse`/`environment`, then preserve each target’s dependency metadata
- Delete: Fabric soft delete (`DELETE .../notebooks/{id}`)

### Dataflow Gen1

- Format: CDM `model.json`
- API: Power BI (`api.powerbi.com`), not Fabric Items (Gen1 is not listed by Fabric Dataflow APIs)
- Deploy: **create only** (workspace targets); import strips entity `partitions`; `nameConflict=Abort`
- Compare: normalized JSON unified diff (partitions ignored)
- Delete: Power BI `DELETE .../dataflows/{id}`
- After create, credentials/connections must be configured in the service (not in JSON)

## Commands agents should know

See [DEVELOPMENT.md](DEVELOPMENT.md) for full install/test/build steps.

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m fabric_tools --version
py -3 -m fabric_tools notebook --help
py -3 -m fabric_tools dataflow-gen1 --help
py -3 -m ruff check .
py -3 -m ruff format --check .
py -3 -m pytest
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

Prefer `py -3` on this machine when the default `python` is not 3.11+.

Do not commit `dist/` or `build/`. Keep `packaging/fabric-tools.spec` checked in.
