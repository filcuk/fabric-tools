# <img src="res/app.svg" alt="" width="40" height="40" align="left"> Fabric Tools

CLI for working with Microsoft Fabric artifacts.

## Quick start

Download the single `fabric-tools.exe` release. You can run it as-is, or install it for faster startup:

```powershell
.\fabric-tools.exe setup install
```

Open a new terminal (restart your IDE if the command is not found) and get started:

```powershell
fabric-tools --help
fabric-tools notebook --help
fabric-tools dataflow-gen1 --help
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

## Support

- Notebooks
  - `.ipynb` — Jupyter notebook
  - `*.Notebook\` — Fabric Git folder with `notebook-content.*` and `.platform`
  - download, deploy (create/overwrite), compare, delete (soft delete)
- Dataflow Gen1 (Power BI)
  - `model.json` — CDM dataflow definition
  - download, deploy (**create only**), compare, delete
  - Connections/credentials are not in the JSON; configure them in the service after create

## Flags

| Flag | Alias | Purpose |
|------|---------|---------|
| `--target` | `-t` | `workspaceId` (create) or `workspaceId:artifactId` (repeatable or comma-separated). Overwrite CSV: one workspace per `-t` (bare artifact ids inherit that workspace). Create CSV may list multiple workspaces. |
| `--file` | `-f` | Local notebook path/folder or Gen1 `model.json` (repeatable or comma-separated). Optional on download: defaults to remote name + `.ipynb` / `.json` in the current folder. |
| `--origin` | `-o` | Remote `workspaceId:artifactId` source for deploy/compare (mutually exclusive with `--file`; same per-flag shorthand as `--target`) |
| `--manifest` | `-m` | Deployment manifest stem/path (`.ftdep`); load and/or write |
| `--silent` | `-s` | Skip confirmation prompts |
| `--dry-run` | `-d` | Validate only (either side may be omitted); with `-m`, writes the manifest on success |
| `--name` | `-n` | Display name for create deploys |
| `--cells` | `-c` | Notebook overwrite only: listed 1-based cells (single local `.ipynb` only) |
| `--interactive` | `-i` | Guided wizard to build a request |

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

# Dataflow Gen1: download / create / compare / delete
fabric-tools dataflow-gen1 download -s -t <workspaceId>:<dataflowId> -f .\model.json
fabric-tools dataflow-gen1 download -s -t <workspaceId>:<dataflowId>
fabric-tools dataflow-gen1 deploy -s -t <workspaceId> -f .\model.json -n "Sales"
fabric-tools dataflow-gen1 compare -t <workspaceId>:<dataflowId> -f .\model.json
fabric-tools dataflow-gen1 delete -s -t <workspaceId>:<dataflowId>

# Dry-run validate and write test.ftdep (no remote changes)
fabric-tools notebook deploy -d -t <workspaceId>:<notebookId> -f .\etl.ipynb -m test

# Deploy and write test.ftdep (create deploys store the new artifact GUID)
fabric-tools notebook deploy -s -t <workspaceId> -f .\etl.ipynb -n "ETL" -m test

# Later compare using only the manifest
fabric-tools notebook compare -m test

# Show what a manifest contains (no Fabric API calls)
fabric-tools inspect -m test

# List all manifests in the current folder
fabric-tools inspect

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

Notebooks use the Fabric API token. Dataflow Gen1 uses a Power BI API token
(same sign-in / service principal; different audience).

For automation, set a service principal:

```powershell
$env:AZURE_TENANT_ID="..."
$env:AZURE_CLIENT_ID="..."
$env:AZURE_CLIENT_SECRET="..."
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
