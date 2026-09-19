# AGENTS.md

Guidance for AI agents and contributors working on this repository.

Human contributor setup (install, pytest, ruff, exe build) is in [DEVELOPMENT.md](DEVELOPMENT.md). End-user CLI docs are in [README.md](README.md). CLI colour and layout design is in [DESIGN.md](DESIGN.md).

## Project goal

`fabric-tools` is a Python CLI (later optionally TUI / Windows `.exe`) for Microsoft Fabric artifacts. Current scope: notebook sync (download/deploy/compare/delete), Dataflow Gen2 sync via Fabric (`dataflow`), Dataflow Gen1 sync via Power BI (`dataflow-gen1`; create-only deploy), DataPipeline sync (`pipeline`), User Data Function sync (`udf`), Environment sync (`environment`), Variable Library sync (`variable-library`), Org App sync (`org-app`), semantic model sync (`semantic-model`; RLS role members via XMLA), report sync (`report`; joins a packable model by default), paginated report sync (`paginated-report`; `.rdl` via Power BI), and read-only `inspect` (list/get workspaces and items).

## Layout

- `src/fabric_tools/` — package root
  - `cli/` — **Typer surface only** (parse options → call sync). Entrypoint stays `fabric_tools.cli:run`.
    - `__init__.py` — exports `app`, `run`
    - `app.py` — root Typer app, banner callback, `add_typer` for every command group
    - `options.py` — shared help strings + Option factories (`origin_opt`, `target_opt`, `manifest_opt`, `silent_opt`, `dry_run_opt`, `name_opt`, `remap_opt`, `filter_opt`, …)
    - `lifecycle.py` — process lifecycle helpers used by the Typer app
    - `commands/` — one module per group: kind sync (`notebook`, `dataflow`, `dataflow_gen1`, `pipeline`, `udf`, `environment`, `variable_library`, `org_app`, `semantic_model`, `report`, `paginated_report`) plus `inspect`, `pack`, `manifest`, `env`, `setup`, hidden `debug`
  - `sync/` — **orchestration API** shared by CLI, interactive, and pack (do not re-export runners from `cli`)
    - `__init__.py` — re-exports all `run_*_command`
    - `common.py` — auth/readonly exits, `_resolve_*_inputs`, manifest write, print helpers, remap pairing, `workspaceId:*` expand labels
    - `orchestrator.py` — `KindSpec`, `SyncRequest`, `run_sync_command` (shared download/deploy/compare/delete skeleton)
    - `kinds/<kind>.py` — thin `run_*_command` facades that build a `KindSpec` and call `run_sync_command` (exception: `semantic_model_role.py` stays a custom XMLA runner)
  - `xmla_roles.py` — Windows PowerShell + SqlServer (PSGallery) client for semantic-model RLS role members (`xmla_role_members.ps1`)
  - `interactive.py` — `--interactive` / `-i` guided wizard (optional `.ftdep` save); calls `fabric_tools.sync`
  - `manifest.py` — deployment manifest (`.ftdep`) load/save/inspect helpers (schema v3 packs: top-level `kind: "pack"`; per-entry `kind`: `notebook` \| `dataflow` \| `dataflow-gen1` \| `pipeline` \| `udf` \| `environment` \| `variable-library` \| `org-app` \| `semantic-model` \| `report` \| `paginated-report`; optional pack/entry `remap` path refs)
  - `pack_run.py` — multi-kind pack orchestration (`fabric-tools pack …`); kind → `run_*_command` map; calls `fabric_tools.sync`
  - `colours.py` — CLI colour roles, help theme, `debug color` swatch (see [DESIGN.md](DESIGN.md))
  - `inspect_cmd.py` — Fabric workspace/item list/get helpers (filters, formatters, `--target` shapes)
  - `path_setup.py` — Windows user install/update/uninstall (`fabric-tools setup …`; Nuitka onefile extracts under `%LOCALAPPDATA%\fabric-tools\cache`, install copies to `app\`; `setup update` downloads release exe and deferred-installs)
  - `setup_status.py` — `setup status` presentation (key/value layout + async GitHub update check); Typer wrapper stays in `cli/commands/setup.py`
  - `update_check.py` — GitHub Releases check (`setup update --check`); once-per-day background notice; release asset download
  - `auth.py` — Azure token acquisition (Fabric + Power BI scopes; SP env, timed WAM broker, browser/device code; persistent cache)
  - `client.py` — Fabric REST client + LRO polling (`get_workspace`, `get_item`, `list_workspaces`, `list_items`)
  - `powerbi_client.py` — Power BI REST client (Gen1 dataflow get/delete/import + poll; report list/export/import; paginated report RDL export/import/delete)
  - `definition_parts.py` — recursive folder ↔ InlineBase64 definition parts
  - `guid_map.py` — deploy `--remap` / `-r` JSON (source GUID → target GUID) load/pair/apply to definition text parts
  - `remote_expand.py` — `workspaceId:*` / `--filter` expansion helpers
  - `parsing.py` — polymorphic `--origin` / `--target` parsing and mode validation (`download` \| `deploy` \| `compare` \| `delete`; `deploy_create_only` for Gen1)
  - `validate.py` — `--dry-run` remote/local checks (Fabric notebooks + Dataflow Gen2 + Power BI Gen1 + DataPipeline + UDF + Environment + Variable Library + Org App + semantic model + report + paginated-report)
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
  - `environment/` — Environment recursive folder pack/unpack (`definition.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
  - `variable_library/` — Variable Library known-part folder pack/unpack (`definition.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
  - `org_app/` — Org App folder pack/unpack (`definition.py`); download/create/overwrite/delete (`ops.py`); compare (`compare.py`)
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
- **Typer never owns business flow** — `cli/commands/*` only parse options and call `fabric_tools.sync.run_*_command`
- **Three frontends, one orchestration API** — CLI, interactive, and pack all call the same `run_*` functions
- CLI colours / aligned tables: use `fabric_tools.colours` roles; do not invent new colours without updating [DESIGN.md](DESIGN.md)
- Lint/format with Ruff (`ruff check` / `ruff format`; config in `pyproject.toml`)
- Do not commit secrets, `.env`, or built `dist/` / `build/` artifacts
- Plan execution: complete one plan step, stop for user review/commit, wait for `continue`
- **Short-alias matching:** a short option letter must match its long option; never reuse a short letter for a different long name; no hidden rename aliases. Before adding/changing flags, update and check [FLAGS.md](FLAGS.md). Breaking migrations go in [BREAKING.md](BREAKING.md).

## Add a kind checklist

When adding a new syncable Fabric / Power BI artifact kind, wire it end-to-end in this order:

1. **Domain package** — `src/fabric_tools/<kind>/` with `definition.py` (pack/unpack + local validate), `ops.py` (download/create/overwrite/delete batches), `compare.py` (unified diff). Prefer Fabric Git-style folders unless the service only exposes another format (e.g. Gen1 `model.json`, paginated `.rdl`).
2. **Confirm + validate** — add overwrite/create/delete prompts in `confirm.py` (name every known affected object unless `-s`); add `run_dry_run_<kind>` in `validate.py`. Cascade / shared-consumer wording must follow the Fabric delete-cascade rule.
3. **Sync KindSpec** — `sync/kinds/<kind>.py` with a stable `run_<kind>_command(**kwargs)` that builds a `KindSpec` and calls `run_sync_command`. Put kind-specific flags (publish, schedules, cells, independent, …) on `SyncRequest` / `validate_flags` / hooks — do not fork the orchestrator control flow. Register the runner in `sync/__init__.py`.
4. **Resolve / expand** — add `_resolve_<kind>_inputs` (and deploy-name helper if needed) in `sync/common.py`; extend `_list_items_fn_for_kind` / `_KIND_EXPAND_LABELS` when `workspaceId:*` applies.
5. **Pack** — add `KIND_*` in `manifest.py`; map it in `pack_run.py`’s kind → runner dict (and any kind-specific kwargs such as publish / schedules / independent). Update deploy/delete kind ordering in `group_pack_entries_by_kind` when order matters.
6. **CLI** — thin `cli/commands/<kind>.py` using `cli/options.py` factories for shared flags; kind-local extras stay in the command module. Register with `app.add_typer` in `cli/app.py`.
7. **Interactive** — tool choice + mode branches in `interactive.py` (and any post-execute save extras).
8. **Docs + tests** — update [FLAGS.md](FLAGS.md) for any new short/long options; document the kind in [README.md](README.md) and this file’s Layout / CLI contract; add unit tests under `tests/` (CliRunner help, dry-run paths, and kind-specific ops/compare as needed).

## CLI contract

### Shared

- **From → to:** `--origin` / `-o` is where content comes from (local path **or** remote selector). `--target` / `-t` is where it goes / the destination (local path **or** remote selector, by mode). Repeatable or comma-separated (spaces after commas OK). Overwrite CSV is one workspace per flag value (bare artifact GUIDs inherit that workspace; use separate flags for other workspaces). Create CSV may list multiple workspaces.
- **Remote selectors:** `workspaceId`, `workspaceId:itemId`, or `workspaceId:*` (all items of the command’s kind in that workspace). Bare item GUID shorthand still works inside a CSV after a qualified piece.
- **`--filter` / `-f`:** case-insensitive `displayName` substring; **only** valid when at least one remote uses `workspaceId:*` (applied to every `*` side in the invocation). Zero matches → error. Not stored in manifests (`*` / filters rejected in `.ftdep`; expand before save).
- **Download:** `-o <workspaceId:artifactId|workspaceId:*>` required; optional `-t <local path>` (defaults to remote display name + kind extension).
- **Deploy / compare:** `-o` local path or remote source; `-t` remote destination (`workspaceId:*` expands to overwrites, never create). Deploy may broadcast one origin to N targets; compare is 1:1 (unequal post-expand counts fail).
- **Delete:** `-t` workspace:artifact or `workspaceId:*` only (no `--origin`); optional `-m` load when entries have `itemId` (manifest not rewritten after delete).
- Manifests: `--manifest` / `-m` stem → `.ftdep`; alone loads pairs; on success or successful dry-run rewrites when content changed (create execute backfills `itemId`; identical content is left alone with no “Wrote manifest” line). **Schema v3 only** (`kind: "pack"`; each entry has its own `kind`; schemaVersion 1/2 unsupported). Optional pack-level and per-entry `remap` path refs to GUID map JSON (relative to the `.ftdep`); CLI `--remap` / `-r` overrides for that run. Homogeneous packs work with kind-specific commands; mixed packs use `pack download|deploy|compare|delete`. Deploy order starts semantic-model → report → variable-library → environment, then consumers and other kinds; delete reverses kind groups. `manifest inspect` one-line summaries in cwd; `manifest inspect -m` dumps one file, or one-line summaries when `-m` is a folder; `manifest list` filenames only; `manifest delete` / `move` local `.ftdep` files (confirm unless `-s`). Interactive may offer save after execute or dry-run (optional pack-level remap path).
- Flags: `--silent` / `-s`, `--dry-run` / `-d` (see [FLAGS.md](FLAGS.md))
- Auth: interactive default; Windows WAM silent reuse, then interactive WAM (skipped in IDE/non-TTY, otherwise 45s timeout) then browser then device code; service principal via `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` (not supported for `udf`)
- Read-only (agents): `FABRIC_TOOLS_READONLY=1` refuses deploy/delete execute, semantic-model role member add/remove execute, and `setup install` / `setup update` (install) / `setup uninstall` / `setup clean`. Allows download, compare, `inspect`, `manifest inspect` / `list` / `delete` / `move`, `--dry-run`, `semantic-model role list`, `setup status`, `setup update --check`. `--silent` does not override.
- Env report: `fabric-tools env list` lists supported env vars (`FABRIC_TOOLS_*`, `AZURE_*`) and current process values (`AZURE_CLIENT_SECRET` redacted). `env set` / `env unset` persist catalogued names in the Windows user environment (new terminal needed for other shells; secret values never echoed). Allowed under read-only.
- Setup (Windows): `setup install` / `setup update` / `setup update --check` / `setup status` / `setup clean` / `setup uninstall`. Background update notice at most once per local day (opt out: `FABRIC_TOOLS_DISABLE_UPDATE_CHECK=1`). `setup update` downloads the release `fabric-tools.exe` and deferred-installs into `%LOCALAPPDATA%\fabric-tools\app` (works from the installed/portable exe or a Python install; install dir is prepended on user PATH). Release builds use Nuitka onefile (`scripts/build_exe.ps1`). `setup status` uses the same key/value layout as inspect get (dim right-aligned keys, no colons; see [DESIGN.md](DESIGN.md)); it shows a Version row (installed PE version when available) and runs an async GitHub update check (yellow `installed < latest` when behind).

### Inspect (`inspect`)

- Read-only Fabric Core browse: `inspect workspace list|get`, `inspect item list|get` (not local `manifest inspect`)
- `--target` / `-t`: workspace GUID for workspace get / item list; `workspaceId:itemId` for item get
- `--filter` / `-f`: case-insensitive `displayName` substring
- `--artifact` / `-a`: Fabric type filter — workspace types (`Personal`, `Workspace`, `AdminWorkspace`) or item types (`Notebook`, `Dataflow`, …); inspect-scoped (not root `--interactive`)
- List: aligned columns with header row (Rich: name default, other columns dim; headers blue). Workspace: `NAME ID TYPE CAPACITY DOMAIN`. Item: `NAME TARGET TYPE` (`TARGET` = `workspaceId:itemId`). Get: aligned key/value columns (dim **right-aligned** keys, left-aligned default values; no colons)
- Item list passes `--artifact` through to the Fabric `type` query param; name filter is client-side
- Scope is what the signed-in principal can access (Personal / My workspace included for user auth; typically not for service principal)

### Notebooks

- Formats: `.ipynb` or Fabric Git `.Notebook` folder
- Deploy: create or overwrite; overwrite may use `--cells` / `-c` (1-based, single local `.ipynb` only)
- Full `.ipynb` overwrite: merge omitted `metadata.dependencies` (`lakehouse`, `environment`) from remote before `updateDefinition`
- Origin overwrite: strip origin `lakehouse`/`environment`, then preserve each target’s dependency metadata
- Deploy `--remap` / `-r`: rewrite source→target GUIDs in definition text before create/update (skips `.platform`); overwrite preserve of lakehouse/environment still runs after remap
- Delete: Fabric soft delete (`DELETE .../notebooks/{id}`)

### Dataflow Gen2 (`dataflow`)

- Format: Fabric Git-style `*.Dataflow` folder (`queryMetadata.json`, `mashup.pq`; optional `.platform`, `*.mdf`)
- API: Fabric Items / Dataflow (`api.fabric.microsoft.com`), item type `Dataflow` (same Fabric auth as notebooks)
- Deploy: create or overwrite (`updateDefinition`; `updateMetadata=true` when `.platform` is present)
- Compare: multi-part unified diff (JSON parts pretty-printed with `sort_keys`; mashup as text)
- Delete: Fabric soft delete (`DELETE .../dataflows/{id}`)
- Connection IDs / lakehouse GUIDs in mashup and metadata are environment-specific; use deploy `--remap` / `-r` to rewrite source→target GUIDs in memory (skips `.platform`)
- Deploy alone does not publish; opt-in `--publish` / `-p` runs Fabric Apply Changes after each successful create/update (prepare for refresh; same preparation as UI Save). User identity only (not service principal)
- Deploy `--remap` / `-r`: JSON object of GUID→GUID; one file may broadcast to all targets, or pair 1:1 with targets (not on download/compare/delete)

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
- Activity references (notebook / lakehouse / connection GUIDs) are environment-specific; use deploy `--remap` / `-r` to rewrite source→target GUIDs in memory before create/update (skips `.platform`; local folders unchanged)
- Deploy `--remap` / `-r`: JSON object of GUID→GUID; one file may broadcast to all targets, or pair 1:1 with targets (not on download/compare/delete)

### User Data Functions (`udf`)

- Format: Fabric Git-style `*.UserDataFunction` folder (`definition.json`, `function_app.py`, `resources/functions.json`; optional `.platform`, `privateLibraries/*.whl`). Pack also accepts Git aliases `definitions.json` / `function-app.py` and normalizes to REST paths.
- API: Fabric UserDataFunction (`/workspaces/{ws}/userDataFunctions/...`), same Fabric auth scope as notebooks
- Auth: **user identity only** — service principal is rejected up front (`check_udf_user_auth`)
- Deploy: create or overwrite; overwrite preserves target `connectedDataSources` (origin overwrite strips origin connections first, then applies each target’s)
- Deploy `--remap` / `-r`: rewrite source→target GUIDs in definition text before create/update (skips `.platform` / `.whl`); overwrite `connectedDataSources` preserve still runs after remap
- Compare: multi-part unified diff (JSON pretty-printed; `.whl` parts reported as `<binary N bytes>`)
- Delete: Fabric soft delete (`DELETE .../userDataFunctions/{id}`)

### Org Apps (`org-app`)

- Format: Fabric Git-style `*.OrgApp` folder (`definition.json` required; optional `.platform`)
- API: Fabric Org App (`/workspaces/{ws}/orgApps/...` + create via `/items` with type `OrgApp`)
- Deploy: create or overwrite (`updateDefinition`; `updateMetadata=true` when `.platform` is present)
- Compare: normalized JSON unified diff of `definition.json`
- Delete: Fabric soft delete (`DELETE .../orgApps/{id}`)
- No GUID remap or publish option

### Variable Libraries (`variable-library`)

- Format: Fabric Git-style `*.VariableLibrary` folder with required `variables.json` and `settings.json`; optional `valueSets/*.json` and `.platform`. Legacy `valueSet/` input is accepted and normalized to `valueSets/`.
- API: Fabric Variable Library (`/workspaces/{ws}/variableLibraries/...` + create via `/items` with type `VariableLibrary`)
- Deploy: create or overwrite (`updateDefinition`; `updateMetadata=true` when `.platform` is present)
- Compare: stable multi-part JSON diff; `.platform` excluded and JSON keys sorted
- Delete: Fabric soft delete (`DELETE .../variableLibraries/{id}`)
- No GUID remap or publish option. Variable Library is the service-native promotion path for values; `--remap` remains for GUID rewriting in other item definitions. Sync does not bind or apply library values to pipelines or notebooks automatically.

### Environments (`environment`)

- Format: Fabric Git-style `*.Environment` folder with one or more definition files under `Libraries/`, `Setting/Sparkcompute.yml`, or `.platform`
- API: Fabric Environment (`/workspaces/{ws}/environments/...` + create via `/items` with type `Environment`)
- Deploy: create or overwrite (`updateDefinition`; `updateMetadata=true` when `.platform` is present)
- Compare: stable multi-part diff; `.platform` excluded, text normalized, binary libraries shown as `<binary N bytes>`
- Delete: Fabric soft delete (`DELETE .../environments/{id}`)
- No GUID remap or publish option. Definition sync updates staging content only; it does not publish. Users may still need `POST .../environments/{id}/staging/publish?beta=false` (or the Fabric UI) after deploy for changes to become effective.

### Semantic models (`semantic-model`)

- Format: Fabric Git-style `*.SemanticModel` folder (`definition.pbism` required; TMDL `definition/` **or** TMSL `model.bim`, not both)
- API: Fabric SemanticModel (`/workspaces/{ws}/semanticModels/...` + create via `/items` with type `SemanticModel`)
- Deploy: create or overwrite (`updateDefinition`; `updateMetadata=true` when `.platform` is present); `--independent` / `-i` reserved for future thick `.pbix` (`skipReport`); no-op for folders
- Compare: multi-part unified diff (relative paths; JSON/`.pbism`/`.bim` pretty-printed)
- Delete: Fabric soft delete; service also removes dependent reports — confirm lists known consumers in the workspace (Power BI report list, best-effort); **no** `--independent` (cascade cannot be opted out)
- Overwrite confirm lists other reports bound to the model (best-effort)
- Role membership (`semantic-model role list|member add|member remove`): Windows-only; PowerShell + SqlServer (PSGallery) TOM over XMLA; `-t` / `workspaceId:*` / `-f`; membership only (not DAX filters); capacity needs XMLA read/write; personal (My) workspace uses XMLA v2 URL from token claims and requires a non-null `capacityId` (preflight `xmla_capacity_required`); staged spinner (`connecting via XMLA` → `loading model` → mutate/save); hard connect watchdog + timeouts via `FABRIC_TOOLS_XMLA_TIMEOUT` (25s) / `FABRIC_TOOLS_XMLA_CONNECT_TIMEOUT` (15s); failures include stage; `FABRIC_TOOLS_READONLY` blocks member add/remove execute (dry-run allowed); SqlServer module checked once up front outside any spinner — missing → offer `Install-Module SqlServer -Scope CurrentUser` (fail fast with hint under `-s`); never prompt under a live spinner

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
py -3 -m fabric_tools environment --help
py -3 -m fabric_tools org-app --help
py -3 -m fabric_tools variable-library --help
py -3 -m fabric_tools semantic-model --help
py -3 -m fabric_tools report --help
py -3 -m fabric_tools paginated-report --help
py -3 -m fabric_tools dataflow-gen1 --help
py -3 -m fabric_tools pipeline --help
py -3 -m fabric_tools udf --help
py -3 -m fabric_tools setup --help
py -3 -m fabric_tools debug color
py -3 -m fabric_tools debug xmla-roles --help
py -3 -m ruff check .
py -3 -m ruff format --check .
py -3 -m pytest
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

Prefer `py -3` on this machine when the default `python` is not 3.11+.

Do not commit `dist/` or `build/`. Keep `packaging/nuitka_options.py` and `packaging/nuitka_entry.py` checked in.
