# <img src="res/app.svg" alt="" width="40" height="40" align="left"> Fabric Tools

CLI for working with Microsoft Fabric artifacts.

## Quick start

Download the single `fabric-tools.exe` release. You can run it as-is (portable, slower startup), or install it for up to ~20× faster launches:

```powershell
.\fabric-tools.exe setup install
```

Portable one-file runs print a yellow stderr warning suggesting install. After install, use the PATH launcher (not the downloaded exe) to get the speedup.

Open a new terminal (restart your IDE if the command is not found) and get started:

```powershell
fabric-tools --help
fabric-tools --interactive
fabric-tools setup update --check
```

Install, update, check status, or remove registration:

```powershell
fabric-tools setup install
fabric-tools setup update
fabric-tools setup status
fabric-tools setup uninstall
```

Commands may print a one-line update notice on stderr at most once per local day when a newer GitHub release exists. Disable with `$env:FABRIC_TOOLS_DISABLE_UPDATE_CHECK=1`.

Set `$env:FABRIC_TOOLS_READONLY=1` to refuse deploy, delete, and mutating `setup` actions (install / update / uninstall). Download, compare, `manifest inspect` / `list` / `delete` / `move`, `--dry-run`, `setup status`, and `setup update --check` still work. Useful for agents.

List or change supported environment variables (Windows user environment for set/unset):

```powershell
fabric-tools env
fabric-tools env set FABRIC_TOOLS_READONLY 1
fabric-tools env set AZURE_TENANT_ID <guid>
fabric-tools env unset AZURE_CLIENT_SECRET
```

`env set` / `env unset` only accept catalogued names. Open a new terminal for other shells to pick up changes. `AZURE_CLIENT_SECRET` is never printed back.

## Support

- Notebooks
  - `.ipynb` — Jupyter notebook
  - `*.Notebook\` — Fabric Git folder with `notebook-content.*` and `.platform`
  - download, deploy (create/overwrite), compare, delete (soft delete)
- Dataflow Gen2 (Fabric)
  - `*.Dataflow\` — Git-style folder with `queryMetadata.json`, `mashup.pq` (optional `.platform`, `*.mdf`)
  - download, deploy (create/overwrite), compare, delete (soft delete)
  - Connection IDs in the definition are environment-specific; Publish may still be needed in the service after sync
- Dataflow Gen1 (Power BI)
  - `model.json` — CDM dataflow definition
  - download, deploy (**create only**), compare, delete
  - Connections/credentials are not in the JSON; configure them in the service after create
- DataPipeline (`pipeline`)
  - `*.DataPipeline\` — Fabric Git folder with `pipeline-content.json` (optional `.platform`, `.schedules`)
  - download, deploy (create/overwrite), compare, delete (soft delete)
  - Default is pipeline-only (omit `.schedules`). `--include-schedules` / `-i` syncs schedules: download writes them; compare includes them; deploy create/overwrite sends source schedules. Overwrite without `-i` reattaches each target's existing `.schedules` so remote schedules stay untouched
  - Activity references (notebooks, lakehouses, connections) are passed through as-is and must be valid in the target workspace
- User Data Functions (`udf`)
  - `*.UserDataFunction\` — Fabric Git-style folder (`definition.json`, `function_app.py`, `resources/functions.json`; optional `.platform`, `privateLibraries/*.whl`)
  - download, deploy (create/overwrite), compare, delete (soft delete)
  - Overwrite preserves the target item’s `connectedDataSources`
  - Fabric APIs require interactive user auth (service principal is not supported)
- Semantic models (`semantic-model`)
  - `*.SemanticModel\` — Fabric Git folder (`definition.pbism` + TMDL `definition/` or TMSL `model.bim`)
  - download, deploy (create/overwrite), compare, delete (soft delete)
  - Delete confirms list dependent reports in the workspace (service removes them with the model)
  - Overwrite confirms list other reports bound to the model
  - Deploy `--independent` / `-i`: reserved for model-only from a packaged report source (e.g. future `.pbix`); no-op for folders; not on delete
- Reports (`report`)
  - `*.Report\` folder or `.pbix` — joins a packable semantic model by default
  - download, deploy (create/overwrite), compare, delete (soft delete; model left intact)
  - `--independent` / `-i`: report only (errors on thick `.pbix` deploy)
  - Overwrite confirms name shared-model consumers; delete confirms note the orphan model when known
- Paginated reports (`paginated-report`)
  - `.rdl` — Power BI Report Builder definition (Power BI API; not Fabric Items definition)
  - download, deploy (create/overwrite), compare, delete
  - Overwrite uses the existing remote report name (`--name` is create-only)
  - Datasources/credentials are not synced; configure them in the service after deploy

## Flags

| Flag | Alias | Purpose |
|------|---------|---------|
| `--target` | `-t` | `workspaceId` (create) or `workspaceId:artifactId` (repeatable or comma-separated). Overwrite CSV: one workspace per `-t` (bare artifact ids inherit that workspace). Create CSV may list multiple workspaces. |
| `--file` | `-f` | Local notebook path/folder, Gen2 `*.Dataflow` folder, Gen1 `model.json`, DataPipeline `*.DataPipeline` folder, UDF `*.UserDataFunction` folder, `*.SemanticModel` folder, `*.Report` folder, `.pbix`, or paginated `.rdl` (repeatable or comma-separated). Optional on download: defaults to remote name + extension in the current folder. |
| `--origin` | `-o` | Remote `workspaceId:artifactId` source for deploy/compare (mutually exclusive with `--file`; same per-flag shorthand as `--target`) |
| `--manifest` | `-m` | Deployment manifest stem/path (`.ftdep`); load and/or write |
| `--silent` | `-s` | Skip confirmation prompts |
| `--dry-run` | `-d` | Validate only (either side may be omitted); with `-m`, writes the manifest on success |
| `--name` | `-n` | Display name for create deploys |
| `--cells` | `-c` | Notebook overwrite only: listed 1-based cells (single local `.ipynb` only) |
| `--interactive` | `-i` | Guided wizard to build a request (root only, before a subcommand: `fabric-tools -i`). Esc or ← Back returns one major step; Ctrl+C cancels |
| `--independent` | `-i` | `report` download/deploy/compare and `semantic-model deploy`: act only on this command’s artifact; not on `semantic-model delete` |
| `--include-schedules` | `-i` | `pipeline` download/deploy/compare: sync `.schedules` (default is pipeline-only; overwrite without `-i` preserves remote schedules; not on delete) |

## Example commands

```powershell
# Dry-run: local file only
fabric-tools notebook deploy -d -f .\etl.ipynb

# Dry-run: remote target only
fabric-tools notebook download -d -t <workspaceId>:<notebookId>

# Download (format inferred from destination path; -f optional → remote name.ipynb)
fabric-tools notebook download -s -t <workspaceId>:<notebookId> -f .\etl.ipynb
fabric-tools notebook download -s -t <workspaceId>:<notebookId>

# Deploy overwrite from local file
fabric-tools notebook deploy -s -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Deploy overwrite only specific cells (1-based; single .ipynb)
fabric-tools notebook deploy -s -t <workspaceId>:<notebookId> -f .\etl.ipynb -c 1,3,5

# Deploy create from local file
fabric-tools notebook deploy -s -t <workspaceId> -f .\etl.ipynb -n "ETL"

# Deploy create to multiple workspaces (same file)
fabric-tools notebook deploy -s -t <ws1>,<ws2> -f .\etl.ipynb -n "ETL"

# Deploy overwrite to two notebooks in the same workspace (shorthand)
fabric-tools notebook deploy -s -t <workspaceId>:<nb1>,<nb2> -f .\etl.ipynb

# Deploy from Fabric origin (e.g. dev) to test and prod (separate -t per workspace)
fabric-tools notebook deploy -s -o <devWs>:<notebookId> -t <testWs>:<notebookId> -t <prodWs>:<notebookId>

# Compare remote vs local
fabric-tools notebook compare -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Compare two Fabric notebooks
fabric-tools notebook compare -o <devWs>:<notebookId> -t <testWs>:<notebookId>

# Soft-delete notebooks
fabric-tools notebook delete -s -t <workspaceId>:<notebookId>

# Dataflow Gen2: download / create / overwrite / compare / delete
fabric-tools dataflow download -s -t <workspaceId>:<dataflowId> -f .\Sales.Dataflow
fabric-tools dataflow download -s -t <workspaceId>:<dataflowId>
fabric-tools dataflow deploy -s -t <workspaceId> -f .\Sales.Dataflow -n "Sales"
fabric-tools dataflow deploy -s -t <workspaceId>:<dataflowId> -f .\Sales.Dataflow
fabric-tools dataflow compare -t <workspaceId>:<dataflowId> -f .\Sales.Dataflow
fabric-tools dataflow delete -s -t <workspaceId>:<dataflowId>

# Dataflow Gen1: download / create / compare / delete
fabric-tools dataflow-gen1 download -s -t <workspaceId>:<dataflowId> -f .\model.json
fabric-tools dataflow-gen1 download -s -t <workspaceId>:<dataflowId>
fabric-tools dataflow-gen1 deploy -s -t <workspaceId> -f .\model.json -n "Sales"
fabric-tools dataflow-gen1 compare -t <workspaceId>:<dataflowId> -f .\model.json
fabric-tools dataflow-gen1 delete -s -t <workspaceId>:<dataflowId>

# DataPipeline: download / create / overwrite / compare / delete
fabric-tools pipeline download -s -t <workspaceId>:<pipelineId> -f .\ETL.DataPipeline
fabric-tools pipeline download -s -t <workspaceId>:<pipelineId>
fabric-tools pipeline download -s -t <workspaceId>:<pipelineId> -i
fabric-tools pipeline deploy -s -t <workspaceId> -f .\ETL.DataPipeline -n "ETL"
fabric-tools pipeline deploy -s -t <workspaceId>:<pipelineId> -f .\ETL.DataPipeline
fabric-tools pipeline deploy -s -t <workspaceId>:<pipelineId> -f .\ETL.DataPipeline -i
fabric-tools pipeline compare -t <workspaceId>:<pipelineId> -f .\ETL.DataPipeline
fabric-tools pipeline compare -t <workspaceId>:<pipelineId> -f .\ETL.DataPipeline -i
fabric-tools pipeline delete -s -t <workspaceId>:<pipelineId>

# User Data Function: download / create / overwrite / compare / delete
fabric-tools udf download -s -t <workspaceId>:<udfId> -f .\Demo.UserDataFunction
fabric-tools udf download -s -t <workspaceId>:<udfId>
fabric-tools udf deploy -s -t <workspaceId> -f .\Demo.UserDataFunction -n "Demo"
fabric-tools udf deploy -s -t <workspaceId>:<udfId> -f .\Demo.UserDataFunction
fabric-tools udf compare -t <workspaceId>:<udfId> -f .\Demo.UserDataFunction
fabric-tools udf delete -s -t <workspaceId>:<udfId>

# Semantic model: download / create / overwrite / compare / delete
fabric-tools semantic-model download -s -t <workspaceId>:<modelId> -f .\Sales.SemanticModel
fabric-tools semantic-model download -s -t <workspaceId>:<modelId>
fabric-tools semantic-model deploy -s -t <workspaceId> -f .\Sales.SemanticModel -n "Sales"
fabric-tools semantic-model deploy -s -t <workspaceId>:<modelId> -f .\Sales.SemanticModel
fabric-tools semantic-model compare -t <workspaceId>:<modelId> -f .\Sales.SemanticModel
fabric-tools semantic-model delete -s -t <workspaceId>:<modelId>

# Report: download / create / overwrite / compare / delete (joins model by default)
fabric-tools report download -s -t <workspaceId>:<reportId> -f .\Sales.Report
fabric-tools report download -s -t <workspaceId>:<reportId> -i
fabric-tools report deploy -s -t <workspaceId> -f .\Sales.Report -n "Sales"
fabric-tools report deploy -s -t <workspaceId> -f .\Sales.pbix -n "Sales"
fabric-tools report deploy -s -t <workspaceId>:<reportId> -f .\Sales.Report
fabric-tools report compare -t <workspaceId>:<reportId> -f .\Sales.Report
fabric-tools report delete -s -t <workspaceId>:<reportId>

# Paginated report: download / create / overwrite / compare / delete
fabric-tools paginated-report download -s -t <workspaceId>:<reportId> -f .\Sales.rdl
fabric-tools paginated-report download -s -t <workspaceId>:<reportId>
fabric-tools paginated-report deploy -s -t <workspaceId> -f .\Sales.rdl -n "Sales"
fabric-tools paginated-report deploy -s -t <workspaceId>:<reportId> -f .\Sales.rdl
fabric-tools paginated-report compare -t <workspaceId>:<reportId> -f .\Sales.rdl
fabric-tools paginated-report delete -s -t <workspaceId>:<reportId>

# Dry-run validate and write test.ftdep (no remote changes)
fabric-tools notebook deploy -d -t <workspaceId>:<notebookId> -f .\etl.ipynb -m test

# Deploy and write test.ftdep (create deploys store the new artifact GUID)
fabric-tools notebook deploy -s -t <workspaceId> -f .\etl.ipynb -n "ETL" -m test

# Later compare using only the manifest
fabric-tools notebook compare -m test

# Show what a manifest contains (no Fabric API calls)
fabric-tools manifest inspect -m test

# One-line summaries for all manifests in the current folder
fabric-tools manifest inspect

# One-line summaries for manifests in a folder
fabric-tools manifest inspect -m .\jobs

# Filenames only
fabric-tools manifest list

# Delete or move a local .ftdep (not a Fabric item)
fabric-tools manifest delete -s -m test
fabric-tools manifest move -s -m test subdir\test1

# Check GitHub Releases for a newer fabric-tools version
fabric-tools setup update --check
fabric-tools setup update -c

# Download and install the newer Windows .exe release (frozen builds only)
fabric-tools setup update
fabric-tools setup update -s
```

## Authentication

Interactive Azure sign-in by default. On Windows, Fabric Tools prefers the OS account
broker, then falls back to browser or device-code auth.

Notebooks, Dataflow Gen2, DataPipeline, User Data Functions, semantic models, and reports
(folders) use the Fabric API token. Dataflow Gen1, paginated reports (`.rdl`), and `.pbix`
import/export use a Power BI API token (same sign-in / service principal; different audience).
Report and semantic-model overwrite/delete confirms may also call Power BI to list reports
bound to a model.

User Data Function APIs do **not** support service principals — use interactive user sign-in for `udf` commands.

For automation, set a service principal:

```powershell
$env:AZURE_TENANT_ID="..."
$env:AZURE_CLIENT_ID="..."
$env:AZURE_CLIENT_SECRET="..."
```

### Troubleshooting

```powershell
# Remove bad cached auth record
Remove-Item "$env:LOCALAPPDATA\fabric-tools\msal-auth-record.json" -ErrorAction SilentlyContinue
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (compare: all pairs identical; `setup update --check`: up to date) |
| `1` | Validation error, user abort, compare found differences, or newer release available |
| `2` | Fabric / Power BI API or operation failure (also: update check network/API failure) |

## Development

Build instructions for contributors are in [DEVELOPMENT.md](DEVELOPMENT.md).

## License

See [LICENSE](LICENSE).

For Python install, tests, and building the `.exe`, see [DEVELOPMENT.md](DEVELOPMENT.md).
