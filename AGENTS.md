# AGENTS.md

Guidance for AI agents and contributors working on this repository.

## Project goal

`fabric-tools` is a Python CLI (later optionally TUI / Windows `.exe`) for Microsoft Fabric. Phase 1: notebook download/upload sync only.

## Layout

- `src/fabric_tools/` — package root
  - `cli.py` — Typer entrypoint (`fabric-tools`)
  - `auth.py` — Azure / Fabric token acquisition (SP env + interactive/device code)
  - `client.py` — Fabric REST client + LRO polling (`get_workspace`, `get_item`)
  - `confirm.py` — overwrite / create prompts (planned)
  - `notebook/` — definition pack/unpack (`definition.py`); sync ops planned
- `tests/` — unit tests (planned)
- `packaging/` — PyInstaller spec (planned)
- `scripts/` — build helpers (planned)

## Conventions

- Python 3.11+, `src/` layout, Hatchling build
- CLI framework: Typer; HTTP: httpx; auth: azure-identity
- Prefer small, focused modules over large catch-all files
- Do not commit secrets, `.env`, or built `dist/` / `build/` artifacts
- Plan execution: complete one plan step, stop for user review/commit, wait for `continue`

## Phase 1 CLI contract (target)

- Targets: `--target <workspaceId>:<artifactId>` (create: `--target <workspaceId>` only)
- Files: `--file` paired 1:1 with targets, or one file broadcast to N targets
- Formats: `.ipynb` or Fabric Git `.Notebook` folder
- Flags: `--silent`, `--dry-run`
- Auth: interactive default; service principal via `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET`

## Commands agents should know

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m fabric_tools --version
py -3 -m pytest
```

Prefer `py -3` on this machine when the default `python` is not 3.11+.
