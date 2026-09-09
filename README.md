# <img src="res/app.svg" alt="" width="40" height="40" align="left"> Fabric Tools

CLI for working with Microsoft Fabric artifacts.

## Quick start

Register the tool:

```powershell
.\fabric-tools.exe path install
```

Open a new terminal and get started with the following:

```powershell
fabric-tools --help
fabric-tools notebook --help
fabric-tools --interactive
```

Check or remove registration:

```powershell
fabric-tools path status
fabric-tools path uninstall
```

## Support

- Notebooks
  - `.ipynb` — Jupyter notebook
  - `*.Notebook\` — Fabric Git folder with `notebook-content.*` and `.platform`

## Flags

| Flag | Alias | Purpose |
|------|---------|---------|
| `--target` | `-t` | `workspaceId` (create) or `workspaceId:artifactId` (repeatable or comma-separated) |
| `--file` | `-f` | Local `.ipynb` or `*.Notebook` folder (repeatable or comma-separated) |
| `--manifest` | `-m` | Deployment manifest stem/path (`.ftdep`); load and/or write |
| `--silent` | `-s` | Skip confirmation prompts |
| `--dry-run` | `-d` | Validate only (either side may be omitted); with `-m`, writes the manifest on success |
| `--name` | `-n` | Display name for create uploads |
| `--cells` | `-c` | Overwrite only listed 1-based cells (single `.ipynb`) |
| `--interactive` | `-i` | Guided wizard to build a request |

## Example commands

```powershell
# Dry-run: local file only
fabric-tools notebook upload -d -f .\etl.ipynb

# Dry-run: remote target only
fabric-tools notebook download -d -t <workspaceId>:<notebookId>

# Download (format inferred from destination path)
fabric-tools notebook download -s -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Overwrite remote
fabric-tools notebook upload -s -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Overwrite only specific cells (1-based; single .ipynb)
fabric-tools notebook upload -s -t <workspaceId>:<notebookId> -f .\etl.ipynb -c 1,3,5

# Create remote
fabric-tools notebook upload -s -t <workspaceId> -f .\etl.ipynb -n "ETL"

# Compare remote vs local
fabric-tools notebook compare -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Dry-run validate and write test.ftdep (no remote changes)
fabric-tools notebook upload -d -t <workspaceId>:<notebookId> -f .\etl.ipynb -m test

# Upload and write test.ftdep (create uploads store the new artifact GUID)
fabric-tools notebook upload -s -t <workspaceId> -f .\etl.ipynb -n "ETL" -m test

# Later compare using only the manifest
fabric-tools notebook compare -m test

# Show what a manifest contains (no Fabric API calls)
fabric-tools inspect -m test

# List all manifests in the current folder
fabric-tools inspect
```

## Authentication

Interactive Azure sign-in by default. On Windows, Fabric Tools prefers the OS account
broker (Web Account Manager — the same signed-in work account Teams/Office use), then
falls back to browser or device-code auth. Tokens and an auth record are cached under
`%LOCALAPPDATA%\fabric-tools` so later commands can stay silent until the session expires.

For automation, set a service principal:

```powershell
$env:AZURE_TENANT_ID="..."
$env:AZURE_CLIENT_ID="..."
$env:AZURE_CLIENT_SECRET="..."
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (compare: all pairs identical) |
| `1` | Validation error, user abort, or compare found differences |
| `2` | Fabric API / operation failure |

## Development

Build instructions for contributors are in [DEVELOPMENT.md](DEVELOPMENT.md).

## License

See [LICENSE](LICENSE).

For Python install, tests, and building the `.exe`, see [DEVELOPMENT.md](DEVELOPMENT.md).
