# fabric-tools

CLI for working with Microsoft Fabric artifacts.

Phase 1 supports **notebook** download, upload (create/overwrite), and compare between Fabric and local files.

## Get started

Use the standalone Windows executable (no Python install required):

```powershell
.\fabric-tools.exe --help
.\fabric-tools.exe notebook --help
.\fabric-tools.exe --interactive
```

### Register on PATH

So you can run `fabric-tools` from any new terminal:

```powershell
.\fabric-tools.exe path install
```

Then open a **new** terminal and run:

```powershell
fabric-tools --help
fabric-tools path status
```

To undo:

```powershell
fabric-tools path uninstall
```

This copies the tool into `%LOCALAPPDATA%\fabric-tools\bin` and adds that folder to your user PATH.

Build instructions for contributors are in [DEVELOPMENT.md](DEVELOPMENT.md).

## Flags

| Flag | Aliases | Purpose |
|------|---------|---------|
| `--target` | `-t`, `--t` | `workspaceId` (create) or `workspaceId:artifactId` |
| `--file` | `-f`, `--f` | Local `.ipynb` or `*.Notebook` folder |
| `--silent` | `-s`, `--s` | Skip confirmation prompts |
| `--dry-run` | `--dr` | Validate only (either side may be omitted) |
| `--name` | `-n` | Display name for create uploads |
| `--interactive` | `-i`, `--i` | Guided wizard to build a request |

## Notebook commands

```powershell
# Dry-run: local file only
.\fabric-tools.exe notebook upload --dr --f .\etl.ipynb

# Dry-run: remote target only (requires sign-in)
.\fabric-tools.exe notebook download --dr `
  --t 11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222

# Download (format inferred from destination path)
.\fabric-tools.exe notebook download --s `
  --t <workspaceId>:<notebookId> --f .\etl.ipynb

# Overwrite remote
.\fabric-tools.exe notebook upload --s `
  --t <workspaceId>:<notebookId> --f .\etl.ipynb

# Create remote (prints workspaceId:itemId on success)
.\fabric-tools.exe notebook upload --s `
  --t <workspaceId> --f .\etl.ipynb --n "ETL"

# Compare remote vs local (nbdime for .ipynb; text diff for *.Notebook)
.\fabric-tools.exe notebook compare `
  --t <workspaceId>:<notebookId> --f .\etl.ipynb

# Guided interactive setup
.\fabric-tools.exe -i
```

### Local formats

- `.ipynb` — Jupyter notebook
- `*.Notebook\` — Fabric Git folder with `notebook-content.*` and `.platform`

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (compare: all pairs identical) |
| `1` | Validation error, user abort, or compare found differences |
| `2` | Fabric API / operation failure |

## Authentication

Default: interactive Azure sign-in (browser, then device code).

For automation, set a service principal:

```powershell
$env:AZURE_TENANT_ID="..."
$env:AZURE_CLIENT_ID="..."
$env:AZURE_CLIENT_SECRET="..."
```

Unsigned `.exe` builds may trigger SmartScreen warnings.

## License

See [LICENSE](LICENSE).

For Python install, tests, and building the `.exe`, see [DEVELOPMENT.md](DEVELOPMENT.md).
