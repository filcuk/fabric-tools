# Design

CLI visual and interaction design for `fabric-tools`. End-user usage is in [README.md](README.md); contributor setup is in [DEVELOPMENT.md](DEVELOPMENT.md); agent-oriented notes are in [AGENTS.md](AGENTS.md).

## CLI colours

Terminal output uses a fixed role → colour contract. Prefer the shared helpers in `fabric_tools.colours` over ad-hoc `typer.colors` / Rich style strings. Do not introduce new colours without updating this document.

### Palette

| Role | Style | Mechanism | Typical use |
|------|--------|-----------|-------------|
| Error / failure | red | Typer `fg=RED` / Rich `"red"` | Exceptions, failed ops, dry-run failures |
| Warning / cancel / soft fail | yellow | Typer `fg=YELLOW` / Rich `"yellow"` | User cancel, notices, soft errors, partial env state |
| Success / affirmative | green | Typer `fg=GREEN` / Rich `"green"` | Confirmations, successful ops, compare `identical`, enabled/set |
| Identifier / command hint | cyan | Typer `fg=CYAN` / Rich `"cyan"` | Created GUIDs (`workspaceId:itemId`), suggested commands, compare section headers |
| Command option (help) | magenta | Typer Rich help theme | Long options and short aliases in `--help` |
| Muted hint | dim | Typer `dim=True` | Secondary prose before a cyan command hint (not `bright_black`) |
| Secondary columns / keys | dim | Rich `"dim"` | Inspect list non-name columns; inspect get / setup status keys |
| Table headers | bold blue | Rich `"bold blue"` | Inspect list header row |
| Primary text | default | no colour | Names, values, plain echoes, spinner messages, unified diffs |

### Aligned key / value and table layout

Shared formatting rules for multi-column / key-value CLI output:

- **Column gap:** two spaces between columns (`"  "`).
- **No trailing colon** on keys or header labels (use `Status`, not `Status:`).
- **Key / value rows** (inspect get, setup status): left column is the key, **right-aligned** within the widest key width, styled **dim**; value column is **left-aligned** primary text (or a semantic colour when the value itself is a status token).
- **List tables** (inspect workspace/item list): header row is **bold blue**; first data column (name) is primary; remaining columns are **dim**.

Example setup status shape:

```text
 Status  installed
Install  C:\Users\...\fabric-tools\app
   PATH  registered
  Cache  no
```

### Env report statuses

| Status token | Style |
|--------------|--------|
| `enabled` / `set` | green |
| `set (not enabled)` | yellow |
| `unset` / `off` / `not configured` | dim |

### Help theme

At CLI startup, Typer Rich help styles for options are set so **both** long options (`--target`) and short aliases (`-t`) render in magenta (`STYLE_OPTION` and `STYLE_SWITCH`).

### Visual swatch

`fabric-tools debug color` (hidden from root `--help`) prints a two-column swatch: colour name in that style, then primary text describing the role. Use it to review terminal rendering after palette changes.

### Out of scope (for now)

- Colouring unified-diff `+/-` lines
- Non-CLI surfaces (future TUI)
