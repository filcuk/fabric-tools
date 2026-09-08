# Fabric Tools

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
| `--target` | `-t` | `workspaceId` (create) or `workspaceId:artifactId` |
| `--file` | `-f` | Local `.ipynb` or `*.Notebook` folder |
| `--manifest` | `-m` | Deployment manifest stem/path (`.ftdep`); load and/or write |
| `--silent` | `-s` | Skip confirmation prompts |
| `--dry-run` | `-d` | Validate only (either side may be omitted) |
| `--name` | `-n` | Display name for create uploads |
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

# Create remote
fabric-tools notebook upload -s -t <workspaceId> -f .\etl.ipynb -n "ETL"

# Compare remote vs local
fabric-tools notebook compare -t <workspaceId>:<notebookId> -f .\etl.ipynb

# Upload and write test.ftdep (create uploads store the new artifact GUID)
fabric-tools notebook upload -s -t <workspaceId> -f .\etl.ipynb -n "ETL" -m test

# Later compare using only the manifest
fabric-tools notebook compare -m test

# Show what a manifest contains (no Fabric API calls)
fabric-tools inspect -m test
```

## Authentication

Interactive Azure sign-in by default.
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
