# Design

CLI visual and interaction design for `fabric-tools`. End-user usage is in [README.md](README.md); contributor setup is in [DEVELOPMENT.md](DEVELOPMENT.md); agent-oriented notes are in [AGENTS.md](AGENTS.md).

## CLI colours

Terminal output uses a fixed role → colour contract. Prefer the shared helpers in `fabric_tools.colours` (once present) over ad-hoc `typer.colors` / Rich style strings. Do not introduce new colours without updating this document.

### Palette

| Role | Style | Mechanism | Typical use |
|------|--------|-----------|-------------|
| Error / failure | red | Typer `fg=RED` / Rich `"red"` | Exceptions, failed ops, dry-run failures |
| Warning / cancel / soft fail | yellow | Typer `fg=YELLOW` / Rich `"yellow"` | User cancel, notices, soft errors, partial env state |
| Success / affirmative | green | Typer `fg=GREEN` / Rich `"green"` | Confirmations, successful ops, compare `identical`, enabled/set |
| Identifier / command hint | cyan | Typer `fg=CYAN` / Rich `"cyan"` | Created GUIDs (`workspaceId:itemId`), suggested commands, compare section headers |
| Command option (help) | magenta | Typer Rich help theme | Long options and short aliases in `--help` |
| Muted hint | dim | Typer `dim=True` | Secondary prose before a cyan command hint (not `bright_black`) |
| Secondary columns / keys | dim | Rich `"dim"` | Inspect list non-name columns; inspect get keys |
| Table headers | bold blue | Rich `"bold blue"` | Inspect list header row |
| Primary text | default | no colour | Names, values, plain echoes, spinner messages, unified diffs |

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
