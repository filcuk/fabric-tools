# fabric-tools

CLI for working with Microsoft Fabric artifacts.

## Status

Phase 1 focuses on **notebook sync** (download / upload) between Fabric and local files. The CLI scaffolding is in place; sync commands are under development.

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

Notebook download/upload options will be documented here as they land.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

## License

See [LICENSE](LICENSE).
