# AGENTS.md

Guidance for AI agents and contributors working on this repository.

Human contributor setup (install, pytest, ruff, exe build) is in [DEVELOPMENT.md](DEVELOPMENT.md). End-user CLI docs are in [README.md](README.md).

## Project goal

`fabric-tools` is a Python CLI (later optionally TUI / Windows `.exe`) for Microsoft Fabric artifacts. Current scope: notebook sync (download/deploy/compare/delete), Dataflow Gen2 sync via Fabric (`dataflow`), Dataflow Gen1 sync via Power BI (`dataflow-gen1`; create-only deploy), DataPipeline sync (`pipeline`), User Data Function sync (`udf`), semantic model sync (`semantic-model`), report sync (`report`; joins a packable model by default), paginated report sync (`paginated-report`; `.rdl` via Power BI), and read-only `inspect` (list/get workspaces and items).

## Layout

- `src/fabric_tools/` — package root
  - `cli.py` — Typer entrypoint (`fabric-tools`), notebook + `dataflow` + `dataflow-gen1` + `pipeline` + `udf` + `semantic-model` + `report` + `paginated-report` + `inspect` groups, `env` (list/set/unset), `manifest` (inspect/list/delete/move), `setup`
  - `interactive.py` — `--interactive` / `-i` guided wizard (optional `.ftdep` save)
  - `manifest.py` — deployment manifest (`.ftdep`) load/save/inspect helpers (`kind`: `notebook` \| `dataflow` \| `dataflow-gen1` \| `pipeline` \| `udf` \| `semantic-model` \| `report` \| `paginated-report`)
  - `inspect_cmd.py` — Fabric workspace/item list/get helpers (filters, formatters, `--target` shapes)
  - `path_setup.py` — Windows user install/update/uninstall (`fabric-tools setup …`; Nuitka onefile extracts under `%LOCALAPPDATA%\fabric-tools\cache`, install copies to `app\`; `setup update` downloads release exe and deferred-installs)
  - `update_check.py` — GitHub Releases check (`setup update --check`); once-per-day background notice; release asset download
  - `auth.py` — Azure token acquisition (Fabric + Power BI scopes; SP env, timed WAM broker, browser/device code; persistent cache)
  - `client.py` — Fabric REST client + LRO polling (`get_workspace`, `get_item`, `list_workspaces`, `list_items`)
  - `powerbi_client.py` — Power BI REST client (Gen1 dataflow get/delete/import + poll; report list/export/import; paginated report RDL export/import/delete)
  - `definition_parts.py` — recursive folder ↔ InlineBase64 definition parts
  - `parsing.py` — `--target` / `--file` / `--origin` parsing and mode validation (`download` \| `deploy` \| `compare` \| `delete`; `deploy_create_only` for Gen1)
  - `validate.py` — `--dry-run` remote/local checks (Fabric notebooks + Dataflow Gen2 + Power BI Gen1 + DataPipeline + UDF + semantic model + report + paginated-report)
  - `confirm.py` — overwrite / create / delete prompts
  - `status.py` — Rich spinner / status line for auth and long-running work
  - `exit_codes.py` — CLI exit code constants
  - `readonly.py` — `FABRIC_TOOLS_READONLY` guard (blocks deploy/delete execute and mutating setup)
  - `env_info.py` — catalog + report for `fabric-tools env list`; Windows user-env `set` / `unset` for catalogued vars
  - `notebook/` — definition pack/unpack (`definition.py`); selective cell merge (`cells.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`, nbdime)
  - `dataflow/` — Gen2 Git-style folder pack/unpack (`definition.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
  - `dataflow_gen1/` — `model.json` helpers (`definition.py`); download/create/delete (`ops.py`); compare (`compare.py`)
  - `pipeline/` — DataPipeline Git-style folder pack/unpack (`definition.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
  - `udf/` — User Data Function folder pack/unpack (`definition.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
  - `semantic_model/` — semantic model folder pack/unpack (`definition.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
  - `report/` — report folder + PBIX (`definition.py`); join/bind rewrite; download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
  - `paginated_report/` — `.rdl` helpers (`definition.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
- `tests/` — unit tests
- `packaging/nuitka_options.py` — shared Nuitka onefile flags
- `packaging/nuitka_entry.py` — Nuitka compilation entrypoint
- `scripts/build_exe.ps1` — Nuitka onefile build → `dist/fabric-tools.exe`

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
- Files: `--file` paired 1:1 with targets, or one file broadcast to N targets (deploy/download). Download may omit `--file` (defaults to remote display name + `.ipynb` / `.Dataflow` / `.json` / `.DataPipeline` / `.UserDataFunction` / `.rdl` in the current folder).
- Origins: `--origin` / `-o` `<workspaceId>:<artifactId>` for deploy/compare (mutually exclusive with `--file`; same per-flag shorthand as targets; deploy may broadcast one origin to N targets; compare is 1:1)
- Delete: `--target` workspace:artifact only (no `--file`/`--origin`); optional `-m` load when entries have `itemId` (manifest not rewritten after delete)
- Manifests: `--manifest` / `-m` stem → `.ftdep`; alone loads pairs; on success or successful dry-run rewrites (create execute backfills `itemId`). Schema v1 = file sources; v2 adds origin fields. `manifest inspect` one-line summaries in cwd; `manifest inspect -m` dumps one file, or one-line summaries when `-m` is a folder; `manifest list` filenames only; `manifest delete` / `move` local `.ftdep` files (confirm unless `-s`). Interactive may offer save after execute or dry-run.
- Flags: `--silent`, `--dry-run`
- Auth: interactive default; Windows WAM silent reuse, then interactive WAM (skipped in IDE/non-TTY, otherwise 45s timeout) then browser then device code; service principal via `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` (not supported for `udf`)
- Read-only (agents): `FABRIC_TOOLS_READONLY=1` refuses deploy/delete execute and `setup install` / `setup update` (install) / `setup uninstall` / `setup clean`. Allows download, compare, `inspect`, `manifest inspect` / `list` / `delete` / `move`, `--dry-run`, `setup status`, `setup update --check`. `--silent` does not override.
- Env report: `fabric-tools env list` lists supported env vars (`FABRIC_TOOLS_*`, `AZURE_*`) and current process values (`AZURE_CLIENT_SECRET` redacted). `env set` / `env unset` persist catalogued names in the Windows user environment (new terminal needed for other shells; secret values never echoed). Allowed under read-only.
- Setup (Windows): `setup install` / `setup update` / `setup update --check` / `setup status` / `setup clean` / `setup uninstall`. Background update notice at most once per local day (opt out: `FABRIC_TOOLS_DISABLE_UPDATE_CHECK=1`). `setup update` (install) is frozen exe only. Release builds use Nuitka onefile (`scripts/build_exe.ps1`).

### Inspect (`inspect`)

- Read-only Fabric Core browse: `inspect workspace list|get`, `inspect item list|get` (not local `manifest inspect`)
- `--target` / `-t`: workspace GUID for workspace get / item list; `workspaceId:itemId` for item get
- `--filter` / `-f`: case-insensitive `displayName` substring (inspect-scoped; not `--file`)
- `--item` / `-i`: Fabric type filter — workspace types (`Personal`, `Workspace`, `AdminWorkspace`) or item types (`Notebook`, `Dataflow`, …); inspect-scoped (not root `--interactive`)
- List: one line per row (name, ids, type, capacity/domain when present). Get: multi-line field detail
- Item list passes `--item` to the Fabric `type` query param; name filter is client-side
- Scope is what the signed-in principal can access (Personal / My workspace included for user auth; typically not for service principal)

### Notebooks

- Formats: `.ipynb` or Fabric Git `.Notebook` folder
- Deploy: create or overwrite; overwrite may use `--cells` / `-c` (1-based, single local `.ipynb` only)
- Full `.ipynb` overwrite: merge omitted `metadata.dependencies` (`lakehouse`, `environment`) from remote before `updateDefinition`
- Origin overwrite: strip origin `lakehouse`/`environment`, then preserve each target’s dependency metadata
- Delete: Fabric soft delete (`DELETE .../notebooks/{id}`)

### Dataflow Gen2 (`dataflow`)

- Format: Fabric Git-style `*.Dataflow` folder (`queryMetadata.json`, `mashup.pq`; optional `.platform`, `*.mdf`)
- API: Fabric Items / Dataflow (`api.fabric.microsoft.com`), item type `Dataflow` (same Fabric auth as notebooks)
- Deploy: create or overwrite (`updateDefinition`; `updateMetadata=true` when `.platform` is present)
- Compare: multi-part unified diff (JSON parts pretty-printed with `sort_keys`; mashup as text)
- Delete: Fabric soft delete (`DELETE .../dataflows/{id}`)
- Connection IDs / lakehouse GUIDs in mashup and metadata are environment-specific (passed through as-is)
- Publish is not auto-triggered after definition sync; UI save / Publish may still be needed before refresh

### Dataflow Gen1

- Format: CDM `model.json`
- API: Power BI (`api.powerbi.com`), not Fabric Items (Gen1 is not listed by Fabric Dataflow APIs)
- Deploy: **create only** (workspace targets); import strips entity `partitions`; `nameConflict=Abort`
- Compare: normalized JSON unified diff (partitions ignored)
- Delete: Power BI `DELETE .../dataflows/{id}`
- After create, credentials/connections must be configured in the service (not in JSON)

### DataPipeline (`pipeline`)

- Format: Fabric Git-style `*.DataPipeline` folder (`pipeline-content.json` required; optional `.platform`, `.schedules`)
- API: Fabric DataPipeline (`/workspaces/{ws}/dataPipelines/...` + create via `/items` with type `DataPipeline`), same Fabric auth as notebooks
- Deploy: create or overwrite (`updateDefinition`; `updateMetadata=true` when `.platform` is present); default is pipeline-only (omit source `.schedules`); overwrite without `--include-schedules` reattaches each target's existing `.schedules`
- Compare: normalized JSON unified diff of `pipeline-content.json` by default; `.schedules` when `--include-schedules` (`.platform` always excluded)
- `--include-schedules` / `-i` on download/deploy/compare: sync `.schedules` (download writes them; default download also removes a leftover local `.schedules`)
- Delete: Fabric soft delete (`DELETE .../dataPipelines/{id}`)
- Activity references (notebook / lakehouse / connection GUIDs) are passed through as-is; they must be valid in the target workspace (no remapping)

### User Data Functions (`udf`)

- Format: Fabric Git-style `*.UserDataFunction` folder (`definition.json`, `function_app.py`, `resources/functions.json`; optional `.platform`, `privateLibraries/*.whl`). Pack also accepts Git aliases `definitions.json` / `function-app.py` and normalizes to REST paths.
- API: Fabric UserDataFunction (`/workspaces/{ws}/userDataFunctions/...`), same Fabric auth scope as notebooks
- Auth: **user identity only** — service principal is rejected up front (`check_udf_user_auth`)
- Deploy: create or overwrite; overwrite preserves target `connectedDataSources` (origin overwrite strips origin connections first, then applies each target’s)
- Compare: multi-part unified diff (JSON pretty-printed; `.whl` parts reported as `<binary N bytes>`)
- Delete: Fabric soft delete (`DELETE .../userDataFunctions/{id}`)

### Semantic models (`semantic-model`)

- Format: Fabric Git-style `*.SemanticModel` folder (`definition.pbism` required; TMDL `definition/` **or** TMSL `model.bim`, not both)
- API: Fabric SemanticModel (`/workspaces/{ws}/semanticModels/...` + create via `/items` with type `SemanticModel`)
- Deploy: create or overwrite (`updateDefinition`; `updateMetadata=true` when `.platform` is present); `--independent` / `-i` reserved for future thick `.pbix` (`skipReport`); no-op for folders
- Compare: multi-part unified diff (relative paths; JSON/`.pbism`/`.bim` pretty-printed)
- Delete: Fabric soft delete; service also removes dependent reports — confirm lists known consumers in the workspace (Power BI report list, best-effort); **no** `--independent` (cascade cannot be opted out)
- Overwrite confirm lists other reports bound to the model (best-effort)

### Reports (`report`)

- Format: Fabric Git-style `*.Report` folder (`definition.pbir` required; PBIR `definition/` **or** PBIR-Legacy `report.json`) or Power BI `.pbix`
- API: Fabric Report Items for folders; Power BI Import/Export for `.pbix`
- Join by default when a packable model is present (sibling / `byPath` `.SemanticModel`, or thick `.pbix` / `IncludeModel`); thin/live-connect → report only
- Opt-out: `--independent` / `-i` on download/deploy/compare (not delete). Thick `.pbix` + `--independent` → error
- Deploy joined folders: create/update model, rewrite `definition.pbir` to `byConnection`, then report
- Compare: folders/origins only (reject `.pbix`)
- Delete: report only; confirm notes orphan upstream model when known

### Paginated reports (`paginated-report`)

- Format: Power BI Report Builder ``.rdl`` (XML with root `Report`)
- API: Power BI (`api.powerbi.com`) — Fabric Items does **not** expose Get/Update Definition for `PaginatedReport`
- Download: `GET .../reports/{id}/Export` → `.rdl` (rejects `reportType` other than `PaginatedReport`)
- Deploy: create or overwrite via Imports (`nameConflict=Abort` / `Overwrite`); overwrite keys by remote display name (fetched from Get Report); `--name` / `-n` for create only
- Compare: newline-normalized unified text diff of RDL
- Delete: Power BI `DELETE .../reports/{id}`
- After deploy, datasources/credentials must be configured in the service (not in the RDL sync)

## Commands agents should know

See [DEVELOPMENT.md](DEVELOPMENT.md) for full install/test/build steps.

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m fabric_tools --version
py -3 -m fabric_tools inspect --help
py -3 -m fabric_tools notebook --help
py -3 -m fabric_tools dataflow --help
py -3 -m fabric_tools semantic-model --help
py -3 -m fabric_tools report --help
py -3 -m fabric_tools paginated-report --help
py -3 -m fabric_tools dataflow-gen1 --help
py -3 -m fabric_tools pipeline --help
py -3 -m fabric_tools udf --help
py -3 -m fabric_tools setup --help
py -3 -m ruff check .
py -3 -m ruff format --check .
py -3 -m pytest
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

Prefer `py -3` on this machine when the default `python` is not 3.11+.

Do not commit `dist/` or `build/`. Keep `packaging/nuitka_options.py` and `packaging/nuitka_entry.py` checked in.
