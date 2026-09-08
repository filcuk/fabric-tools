# fabric-tools

CLI for working with Microsoft Fabric artifacts.

## Status

Phase 1: **notebook** download, upload (create/overwrite), and compare between Fabric and local files.

## Requirements

- Python 3.11+ (`py -3` on Windows if `python` points at an older runtime)
- Access to a Microsoft Fabric tenant (for live operations)

## Install

```bash
py -3 -m pip install -e ".[dev]"
```

## Quick start

```bash
py -3 -m fabric_tools --help
py -3 -m fabric_tools notebook --help
py -3 -m fabric_tools notebook download --help
py -3 -m fabric_tools --interactive
```

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

```bash
# Dry-run: local file only
py -3 -m fabric_tools notebook upload --dr --f ./etl.ipynb

# Dry-run: remote target only (requires auth)
py -3 -m fabric_tools notebook download --dr \
  --t 11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222

# Download (format inferred from destination path)
py -3 -m fabric_tools notebook download --s \
  --t <workspaceId>:<notebookId> --f ./etl.ipynb

# Overwrite remote
py -3 -m fabric_tools notebook upload --s \
  --t <workspaceId>:<notebookId> --f ./etl.ipynb

# Create remote (prints workspaceId:itemId on success)
py -3 -m fabric_tools notebook upload --s \
  --t <workspaceId> --f ./etl.ipynb --n "ETL"

# Compare remote vs local (nbdime for .ipynb; text diff for *.Notebook)
py -3 -m fabric_tools notebook compare \
  --t <workspaceId>:<notebookId> --f ./etl.ipynb

# Guided interactive setup
py -3 -m fabric_tools -i
```

### Local formats

- `.ipynb` — Jupyter notebook (`format=ipynb`)
- `*.Notebook/` — Fabric Git folder with `notebook-content.*` and `.platform` (`format=fabricGitSource`)

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (compare: all pairs identical) |
| `1` | Validation error, user abort, or compare found differences |
| `2` | Fabric API / operation failure |

## Authentication

Default: interactive Azure sign-in (browser, then device code).

Service principal:

```bash
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
```

## Development

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m pytest
```

## License

See [LICENSE](LICENSE).
