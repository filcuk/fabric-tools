# Design

CLI visual and interaction design for `fabric-tools`. End-user usage is in [README.md](README.md); contributor setup is in [DEVELOPMENT.md](DEVELOPMENT.md); agent-oriented notes are in [AGENTS.md](AGENTS.md).

## CLI colours

Terminal output uses a fixed role → colour contract. Prefer the shared helpers in `fabric_tools.colours` over ad-hoc `typer.colors` / Rich style strings. Do not introduce new colours without updating this document.

### Palette

| Role | Style | Mechanism | Typical use |
|------|--------|-----------|-------------|
| Error / failure | red | Typer `fg=RED` / Rich `"red"`; **Error** panel | All error messages (`print_error_panel` / `_exit_error`), including per-item op/compare failures |
| Warning / cancel / soft fail | yellow | Typer `fg=YELLOW` / Rich `"yellow"`; **Warning** panel | All warning messages (`print_warn_panel` / `_exit_warn`), including compare soft messages and update notices; inline status tokens (e.g. setup status values) stay Rich yellow text only |
| Success / affirmative | green | Typer `fg=GREEN` / Rich `"green"` | Confirmations, successful ops, compare `identical`, enabled/set |
| Identifier / command hint | cyan | Typer `fg=CYAN` / Rich `"cyan"` | Created GUIDs, suggested commands, compare headers, **Usage** command path and `COMMAND` placeholder |
| Help metavar | bright yellow | Typer Rich `STYLE_METAVAR` | Option/argument placeholders in `--help` (e.g. `<PATH>`, `<DEST>`, `<manifest>`, **Usage** `[ARGS]...`); **Power BI** in help text |
| Command option — long (help) | magenta | Typer Rich `STYLE_OPTION` | Long options in `--help` (e.g. `--target`); **Usage** `[OPTIONS]` |
| Command option — alias (help) | bright magenta (`#ff9cf5`) | Typer Rich `STYLE_SWITCH` | Short aliases in `--help` (e.g. `-t`). Truecolor so it stays distinct from magenta when ANSI bright magenta matches magenta. |
| Muted hint | dim | Typer `dim=True` / Rich `"dim"` | Secondary prose; root help subtitle; **Usage:** label |
| Secondary columns / keys | dim | Rich `"dim"` | Inspect list non-name columns; inspect get / setup status keys |
| Table headers | blue | Rich `"blue"` | Inspect list header row |
| Root help — Fabric panel | teal (`#8acfb3`) | Typer Rich `STYLE_COMMANDS_PANEL_BORDER` (patched) | Root `--help` Fabric panel title and frame only (`Local` stays dim) |
| Fabric in help | teal (`#8acfb3`) | Help highlighter `fabric` | The word **Fabric** in help prose (not `fabric-tools`) |
| Root help — banner FABRIC | teal (`#8acfb3`) | Rich truecolor | ASCII art ``FABRIC`` in root `--help` |
| Root help — banner - / TOOLS | `#1d8e7a` | Rich truecolor | ASCII art hyphen gap and ``TOOLS`` in root `--help` |
| Primary text | default | no colour | Names, values, plain echoes, spinner messages, unified diffs |

### Error and warning panels

Every error and warning **message** uses a Rich `Panel` on stderr, matching Typer’s usage-error box:

- **Error** — red border, title `Error`, left-aligned (`fabric_tools.colours.print_error_panel` / `cli._exit_error`).
- **Warning** — yellow border, title `Warning`, left-aligned (`print_warn_panel` / `_exit_warn`).

Do not print error/warning prose with plain coloured `secho`. Success / identifier lines (`identical`, GUIDs, remap ok) stay unboxed `secho`. Inline value colours in tables (setup status, env list) stay Rich styles, not panels. Diff body text stays primary (uncoloured).

### Aligned key / value and table layout

Shared formatting rules for multi-column / key-value CLI output:

- **Column gap:** two spaces between columns (`"  "`).
- **No trailing colon** on keys or header labels (use `Status`, not `Status:`).
- **Key / value rows** (inspect get, setup status): left column is the key, **right-aligned** within the widest key width, styled **dim**; value column is **left-aligned** primary text (or a semantic colour when the value itself is a status token).
- **List tables** (inspect workspace/item list): header row is **blue**; first data column (name) is primary; remaining columns are **dim**.

Example setup status shape:

```text
 Status  installed
Version  0.3.0 (up to date)
Install  C:\Users\...\fabric-tools\app
   PATH  registered
  Cache  no
```

While a GitHub update check runs, the Version value stays green with an inline spinner (`checking…`). When the check finishes: green `0.3.0 (up to date)`, or yellow `0.3.0 < 0.4.0` if a newer release exists. Timeouts show yellow `0.3.0 (update check timeout)`; other check errors show `(update check failed)`. `FABRIC_TOOLS_DISABLE_UPDATE_CHECK` leaves the green installed/running version only.
### Env report statuses

| Status token | Style |
|--------------|--------|
| `enabled` / `set` | green |
| `set (not enabled)` | yellow |
| `unset` / `off` / `not configured` | dim |

### Help theme

At CLI startup, Typer Rich help styles are set so **long options** (`--target`) use magenta (`STYLE_OPTION`), **short aliases** (`-t`) use bright magenta / `#ff9cf5` (`STYLE_SWITCH`), and **metavars** (`<PATH>`, `<DEST>`, `<manifest>`) use bright yellow (`STYLE_METAVAR`). The option highlighter is also patched so `--long` flags are not mis-classified as short switches (Typer’s default patterns make both look identical).

**Usage** lines are highlighted the same way: dim `Usage:` label, cyan command path (`fabric-tools notebook …`) and `COMMAND` placeholder, magenta `[OPTIONS]` / `--flags`, bright yellow argument placeholders (`[ARGS]...`, `<…>`).

In help prose (group/command descriptions and short help), **Fabric** is teal and **Power BI** is bright yellow (`fabric-tools` is left alone).

On **root** `--help` only, the **Fabric** commands panel title and frame use teal (`#8acfb3`); the **Local** panel keeps the default dim border. The ASCII banner colours ``FABRIC`` as `#8acfb3` and the hyphen gap plus ``TOOLS`` as `#1d8e7a`. The subtitle under the banner is **dim**. Subcommand help is unchanged.

### Visual swatch

`fabric-tools debug color` (hidden from root `--help`) prints a two-column swatch using the same alignment as key/value rows: **right-aligned** colour name (in that style), then **left-aligned** primary text describing the role. A single `dim` row covers muted hints and secondary columns/keys. Use it to review terminal rendering after palette changes.

### Out of scope (for now)

- Colouring unified-diff `+/-` lines
- Non-CLI surfaces (future TUI)
