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
| `--origin` | `-o` | Fabric `workspaceId:artifactId` source for deploy/compare (mutually exclusive with `--file`) |
| `--manifest` | `-m` | Deployment manifest stem/path (`.ftdep`); load and/or write |
| `--silent` | `-s` | Skip confirmation prompts |
| `--dry-run` | `-d` | Validate only (either side may be omitted); with `-m`, writes the manifest on success |
| `--name` | `-n` | Display name for create deploys |
| `--cells` | `-c` | Overwrite only listed 1-based cells (single local `.ipynb` only) |
| `--interactive` | `-i` | Guided wizard to build a request |

## Example commands

```powershell
# Dry-run: local file only
fabric-tools notebook deploy -d -f .\etl.ipynb

# Dry-run: remote target only
fabric-tools notebook download -d -t <workspaceId>:<notebookId>

# Download (format inferred from destination path)
fabric-tools notebook download -s -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Deploy overwrite from local file
fabric-tools notebook deploy -s -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Deploy overwrite only specific cells (1-based; single .ipynb)
fabric-tools notebook deploy -s -t <workspaceId>:<notebookId> -f .\etl.ipynb -c 1,3,5

# Deploy create from local file
fabric-tools notebook deploy -s -t <workspaceId> -f .\etl.ipynb -n "ETL"

# Deploy from Fabric origin (e.g. dev) to test and prod
fabric-tools notebook deploy -s -o <devWs>:<notebookId> -t <testWs>:<notebookId>,<prodWs>:<notebookId>

# Compare remote vs local
fabric-tools notebook compare -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Compare two Fabric notebooks
fabric-tools notebook compare -o <devWs>:<notebookId> -t <testWs>:<notebookId>

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
```

## Authentication

Interactive Azure sign-in by default. On Windows, Fabric Tools prefers the OS account
broker, then falls back to browser or device-code auth.

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
