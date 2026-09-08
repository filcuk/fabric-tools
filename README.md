# fabric-tools

CLI for working with Microsoft Fabric artifacts.

## Status

Phase 1 focuses on **notebook sync** (download / upload / compare) between Fabric and local files.

## Requirements

- Python 3.11+ (`py -3` on Windows if `python` points at an older runtime)
- Access to a Microsoft Fabric tenant (for live operations)

## Install

```bash
py -3 -m pip install -e ".[dev]"
```

## Usage

```bash
py -3 -m fabric_tools --version
py -3 -m fabric_tools --help
py -3 -m fabric_tools notebook --help
```

If Scripts is on your PATH, you can also run `fabric-tools` directly.

Flags:

- `--target` / `-t` / `--t` — `workspaceId` (create) or `workspaceId:artifactId` (download/overwrite/compare)
- `--file` / `-f` / `--f` — local `.ipynb` or `*.Notebook` folder
- `--silent` / `-s` / `--s` — skip confirmation prompts
- `--dry-run` / `--dr` — validate only; either side may be omitted
- `--interactive` / `-i` / `--i` — guided prompts to build a request

```bash
# Help
py -3 -m fabric_tools
py -3 -m fabric_tools notebook --help
py -3 -m fabric_tools notebook download --help

# Interactive wizard
py -3 -m fabric_tools --interactive
```

### Notebook commands

```bash
# Validate local notebook path only
py -3 -m fabric_tools notebook upload --dry-run --file ./etl.ipynb

# Validate remote target only (requires auth)
py -3 -m fabric_tools notebook download --dry-run \
  --target 11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222
```

Sync actions:

```bash
# Download (format inferred from destination path)
py -3 -m fabric_tools notebook download --silent \
  --target <workspaceId>:<notebookId> --file ./etl.ipynb

# Overwrite remote
py -3 -m fabric_tools notebook upload --silent \
  --target <workspaceId>:<notebookId> --file ./etl.ipynb

# Create remote (prints workspaceId:itemId on success)
py -3 -m fabric_tools notebook upload --silent \
  --target <workspaceId> --file ./etl.ipynb --name "ETL"

# Compare remote vs local (nbdime for .ipynb; text diff for *.Notebook)
py -3 -m fabric_tools notebook compare \
  --target <workspaceId>:<notebookId> --file ./etl.ipynb
```

Supported local formats:

- `.ipynb` — Jupyter notebook file
- `*.Notebook/` — Fabric Git folder with `notebook-content.*` and `.platform`

## Authentication

By default the CLI uses interactive Azure sign-in (browser, then device code).

For automation, set a service principal:

```bash
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
```

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

## License

See [LICENSE](LICENSE).
