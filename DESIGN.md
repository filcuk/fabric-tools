# Design

CLI visual and interaction design for `fabric-tools`. End-user usage is in [README.md](README.md); contributor setup is in [DEVELOPMENT.md](DEVELOPMENT.md); agent-oriented notes are in [AGENTS.md](AGENTS.md).

## CLI colours

Terminal output uses a fixed role → colour contract. Prefer the shared helpers in `fabric_tools.colours` over ad-hoc `typer.colors` / Rich style strings. Do not introduce new colours without updating this document.

### Palette

| Role | Style | Mechanism | Typical use |
|------|--------|-----------|-------------|
| Error / failure | red | Typer `fg=RED` / Rich `"red"`; **Error** panel | All error messages (`print_error_panel` / `_exit_error`), including per-item op/compare failures |
| Warning / cancel / soft fail | yellow | Typer `fg=YELLOW` / Rich `"yellow"`; **Warning** panel | Command-level warnings and cancel (`print_warn_panel` / `_exit_warn`); update notices; compare STATUS `differences` and other inline status tokens stay Rich yellow text only |
| Success / affirmative | green | Typer `fg=GREEN` / Rich `"green"` | Confirmations, successful ops, compare STATUS `identical`, enabled/set |
| Identifier / command hint | cyan | Typer `fg=CYAN` / Rich `"cyan"` | Created GUIDs, suggested commands, **Usage** command path and `COMMAND` placeholder |
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

Command-level failure and warning messages use a Rich `Panel` on stderr, matching Typer’s usage-error box:

- **Error** — red border, title `Error`, left-aligned (`fabric_tools.colours.print_error_panel` / `cli._exit_error`). Also used for per-item compare failure detail after the summary table.
- **Warning** — yellow border, title `Warning`, left-aligned (`print_warn_panel` / `_exit_warn`) for cancel, soft abort, update notices, and other command-level soft fails.

Do not invent a different boxed style. Success / identifier lines (GUIDs, remap ok) stay unboxed `secho`. Inline value colours in tables (setup status, env list, compare STATUS) stay Rich styles, not panels. Diff body text stays primary (uncoloured). Compare advisories (e.g. joined-model notes) print as **dim** lines after the summary table — not Warning panels.

### Aligned key / value and table layout

Shared formatting rules for multi-column / key-value CLI output:

- **Column gap:** two spaces between columns (`"  "`).
- **No trailing colon** on keys or header labels (use `Status`, not `Status:`).
- **Key / value rows** (inspect get, setup status): left column is the key, **right-aligned** within the widest key width, styled **dim**; value column is **left-aligned** primary text (or a semantic colour when the value itself is a status token).
- **List tables** (inspect workspace/item list): header row is **blue**; first data column (name) is primary; remaining columns are **dim**.
- **Compare summary** (all `compare` commands): header row is **blue**; columns `REMOTE`, `LOCAL`, `STATUS`, `TARGET` (one row per comparison). `REMOTE` / `LOCAL` are primary (display name or local basename — not a full path). `STATUS` is a coloured token (`identical` green, `differences` yellow, `error` red). `TARGET` is dim `workspaceId:itemId`. After the table: Error panels for failed rows, dim advisory notes, then unified diffs for non-identical rows (primary text).

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

### Compare statuses

| Status token | Style |
|--------------|--------|
| `identical` | green |
| `differences` | yellow |
| `error` | red |

### Help theme

At CLI startup, Typer Rich help styles are set so **long options** (`--target`) use magenta (`STYLE_OPTION`), **short aliases** (`-t`) use bright magenta / `#ff9cf5` (`STYLE_SWITCH`), and **metavars** (`<PATH>`, `<DEST>`, `<manifest>`) use bright yellow (`STYLE_METAVAR`). The option highlighter is also patched so `--long` flags are not mis-classified as short switches (Typer’s default patterns make both look identical).

**Usage** lines are highlighted the same way: dim `Usage:` label, cyan command path (`fabric-tools notebook …`) and `COMMAND` placeholder, magenta `[OPTIONS]` / `--flags`, bright yellow argument placeholders (`[ARGS]...`, `<…>`).

In help prose (group/command descriptions and short help), **Fabric** is teal and **Power BI** is bright yellow (`fabric-tools` is left alone).

On **root** `--help` only, the **Fabric** commands panel title and frame use teal (`#8acfb3`); the **Local** panel keeps the default dim border. The ASCII banner colours ``FABRIC`` as `#8acfb3` and the hyphen gap plus ``TOOLS`` as `#1d8e7a`. The subtitle under the banner is **dim**. Subcommand help is unchanged.

### Required options and arguments

Always-required CLI options and arguments must use Typer’s required sentinel (`typer.Option(...)` / `typer.Argument(...)`, or an equivalent with no default). Rich help then shows:

- a leading `*` in the options/arguments table
- a trailing `[required]` on the help line

Example:

```text
│ *  --role     -r      TEXT  Model role name. [required]                      │
│ *  --member           TEXT  Member UPN or Entra group display name …         │
│                             [required]                                       │
```

Do **not** fake this with a `None` default plus `(required)` in the help string — that skips the `*` column and looks inconsistent next to true required flags.

**Conditionally required** flags (e.g. `--origin` / `--target` that are optional when `-m` / `-d` supply enough context) keep a `None` default. Mark them in help prose as `(required without -m or -d)` (or the accurate condition). Do not use `...` for those — Click would reject otherwise-valid invocations.

Optional flags may keep an `(optional)` help prefix for scannability; that is separate from the `*` / `[required]` marker.

When a flag is always required via `...`, omit a redundant `(required)` prefix in the help text — Typer already appends `[required]`.

### Visual swatch

`fabric-tools debug color` (hidden from root `--help`) prints a two-column swatch using the same alignment as key/value rows: **right-aligned** colour name (in that style), then **left-aligned** primary text describing the role. A single `dim` row covers muted hints and secondary columns/keys. Use it to review terminal rendering after palette changes.

### Out of scope (for now)

- Colouring unified-diff `+/-` lines
- Non-CLI surfaces (future TUI)
