# Design

CLI visual and interaction design for `fabric-tools`. End-user usage is in [README.md](README.md); contributor setup is in [DEVELOPMENT.md](DEVELOPMENT.md); agent-oriented notes are in [AGENTS.md](AGENTS.md).

## CLI colours

Terminal output uses a fixed role → colour contract. Prefer the shared helpers in `fabric_tools.colours` over ad-hoc `typer.colors` / Rich style strings. Do not introduce new colours without updating this document.

### Palette

| Role | Style | Mechanism | Typical use |
|------|--------|-----------|-------------|
| Error / failure | red | Typer `fg=RED` / Rich `"red"`; **Error** panel | All error messages (`print_error_panel` / `_exit_error`), including per-item op/compare failures |
| Warning / cancel / soft fail | yellow | Typer `fg=YELLOW` / Rich `"yellow"`; **Warning** panel | Command-level warnings and cancel (`print_warn_panel` / `_exit_warn`); under-spinner notices (`status.warn_aside`); update notices; compare STATUS `differences` and other inline status tokens stay Rich yellow text only |
| Success / affirmative | green | Typer `fg=GREEN` / Rich `"green"` | Confirmations, successful ops, compare STATUS `identical`, enabled/set |
| Identifier / command hint | cyan | Typer `fg=CYAN` / Rich `"cyan"` | Created GUIDs, suggested commands, **Usage** command path and `COMMAND` placeholder |
| Help metavar | bright yellow | Typer Rich `STYLE_METAVAR` | Options/Arguments metavar column (`TEXT`, …); Usage / synopsis placeholders (`<PATH>`, `[ARGS]...`); **Power BI** in help text; optional Rich `[metavar]…[/metavar]` in prose |
| Help required marker (`*`) | red | Typer Rich `STYLE_REQUIRED_SHORT` (pinned in `apply_help_theme`) | Leading `*` on always-required options/arguments in `--help` |
| Help required marker (`[required]`) | dim red | Typer Rich `STYLE_REQUIRED_LONG` (pinned in `apply_help_theme`) | Trailing `[required]` on always-required help lines |
| Command option — long (help) | magenta | Typer Rich `STYLE_OPTION` | Long options in `--help` (e.g. `--target`); **Usage** `[OPTIONS]` |
| Command option — alias (help) | bright magenta (`#ff9cf5`) | Typer Rich `STYLE_SWITCH` | Short aliases in `--help` (e.g. `-t`). Truecolor so it stays distinct from magenta when ANSI bright magenta matches magenta. |
| Muted hint | dim | Typer `dim=True` / Rich `"dim"` | Secondary prose; root help subtitle; **Usage:** label |
| Secondary columns / keys | dim | Rich `"dim"` | Inspect list non-name columns; inspect get / setup status keys |
| Table headers | blue | Rich `"blue"` | Inspect list header row |
| Root help — Fabric panel | teal (`#8acfb3`) | Typer Rich `STYLE_COMMANDS_PANEL_BORDER` (patched) | Root `--help` Fabric panel title and frame only (`Local` stays dim) |
| Fabric in help | teal (`#8acfb3`) | Help highlighter `fabric` | The word **Fabric** in help prose (not `fabric-tools`) |
| Root help — banner FABRIC | teal (`#8acfb3`) | Rich truecolor | ASCII art ``FABRIC`` in root `--help` |
| Root help — banner - / TOOLS | `#1d8e7a` | Rich truecolor | ASCII art hyphen gap and ``TOOLS`` in root `--help` |
| Primary text | default | no colour | Names, values, plain echoes, spinner **text**, unified diffs |
| Activity spinner glyph | green | Rich `"green"` | Dots in `status.busy` / Live spinner only |

### Error and warning panels

Command-level failure and warning messages use a Rich `Panel` on stderr, matching Typer’s usage-error box:

- **Error** — red border, title `Error`, left-aligned (`fabric_tools.colours.print_error_panel` / `cli._exit_error`). Also used for per-item compare failure detail after the summary table.
- **Warning** — yellow border, title `Warning`, left-aligned (`print_warn_panel` / `_exit_warn`) for cancel, soft abort, update notices, and other command-level soft fails.

**Usage errors** (unknown command/option, missing required args, …) print `Usage:` (same highlighting as `--help`) then the Error panel. Do **not** print Typer’s default `Try '… --help' for help.` line — it is suppressed in `apply_help_theme` (`rich_format_error`). The Error panel already carries the useful hint (e.g. Did you mean … / No such option).

Do not invent a different boxed style. Success / identifier lines (GUIDs, remap ok) stay unboxed `secho`. Inline value colours in tables (setup status, env list, compare STATUS) stay Rich styles, not panels. Diff body text stays primary (uncoloured). Compare advisories (e.g. joined-model notes) print as **dim** lines after the summary table — not Warning panels.

### Success / op result lines

Successful download / deploy / delete ops print via `_print_op_results` as unboxed green `secho` of `OpResult.message` (one `OpResult` per work item).

When one op produces **multiple distinct outcomes** (joined report + model, `.pbip` shortcut, deploy model then report, publish follow-up failure after a successful create, …), put **one outcome per line** in `message` (join with `"\n"`, not `"; "`). Parenthetical qualifiers on a single outcome stay on the same line (e.g. `… (published)`, `… (IncludeModel — report + semantic model)`).

Example (joined report download):

```text
downloaded report <ws>:<id> -> temp\Projects.Report
downloaded joined semantic model <ws>:<id> -> temp\Projects.SemanticModel
wrote Power BI Desktop shortcut temp\Projects.pbip
```

Do not glue those into one semicolon-separated line. Error panels may also be multi-line when a partial success is followed by a distinct failure (same newline rule).

### Aligned key / value and table layout

Shared formatting rules for multi-column / key-value CLI output:

- **Column gap:** two spaces between columns (`"  "`).
- **No trailing colon** on keys or header labels (use `Status`, not `Status:`).
- **Key / value rows** (inspect get, setup status): left column is the key, **right-aligned** within the widest key width, styled **dim**; value column is **left-aligned** primary text (or a semantic colour when the value itself is a status token).
- **List tables** (inspect workspace/item list): header row is **blue**; first data column (name) is primary; remaining columns are **dim**.
- **Compare summary** (all `compare` commands): header row is **blue**; columns `REMOTE`, `LOCAL`, `STATUS`, `TARGET` (one row per comparison). `REMOTE` / `LOCAL` are primary (display name or local basename — not a full path). `STATUS` is a coloured token (`identical` green, `differences` yellow, `error` red). `TARGET` is dim `workspaceId:itemId`. After the table, one blank line, then: Error panels for failed rows, dim advisory notes, then unified diffs for non-identical rows (primary text).

Example setup status shape:

```text
 Status  installed
Version  0.3.0 (up to date)
Install  C:\Users\...\fabric-tools\app
   PATH  registered
  Cache  no
```

While a GitHub update check runs on a TTY, the full status block (Status through Cache) is drawn immediately; the Version value stays green with an inline spinner (`checking…`) and is refreshed in place when the check finishes: green `0.3.0 (up to date)`, or yellow `0.3.0 < 0.4.0` if a newer release exists. Timeouts show yellow `0.3.0 (update check timeout)`; other check errors show `(update check failed)`. `FABRIC_TOOLS_DISABLE_UPDATE_CHECK` leaves the green installed/running version only.
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

At CLI startup, Typer Rich help styles are set so **long options** (`--target`) use magenta (`STYLE_OPTION`), **short aliases** (`-t`) use bright magenta / `#ff9cf5` (`STYLE_SWITCH`), and **metavars** use bright yellow (`STYLE_METAVAR`): the Options/Arguments table metavar column (e.g. `TEXT`, styled by Typer), plus Usage / synopsis placeholders (`<PATH>`, `<DEST>`, `[ARGS]...`). Always-required markers use red `*` (`STYLE_REQUIRED_SHORT`) and dim-red `[required]` (`STYLE_REQUIRED_LONG`), pinned in `apply_help_theme`. The option highlighter is also patched so `--long` flags are not mis-classified as short switches (Typer’s default patterns make both look identical).

Do **not** auto-colour bare ALL-CAPS words in help prose (`GUID`, `OK`, `XMLA`, `RLS`, …). To yellow a prose token intentionally, wrap it with `help_metavar(...)` from `fabric_tools.cli.options` (emits Rich `[metavar]…[/metavar]`); use this for selector shapes such as `workspace:artifact`, `workspace:*`, and `workspaceId:itemId`. Unmarked prose stays primary.

**Usage** lines are highlighted the same way: dim `Usage:` label, cyan command path (`fabric-tools notebook …`) and `COMMAND` placeholder, magenta `[OPTIONS]` / `--flags`, bright yellow argument placeholders (`[ARGS]...`, `<…>`).

Usage-error output reuses that Usage line, then the Error panel only — Typer’s `Try '… --help' for help.` hint is omitted (see Error and warning panels).

In help prose (group/command descriptions and short help), **Fabric** is teal and **Power BI** is bright yellow (`fabric-tools` is left alone). Do not grow an acronym highlighter list for other product terms.

On **root** `--help` only, the **Fabric** commands panel title and frame use teal (`#8acfb3`); the **Local** panel keeps the default dim border. The ASCII banner colours ``FABRIC`` as `#8acfb3` and the hyphen gap plus ``TOOLS`` as `#1d8e7a`. The subtitle under the banner is **dim**. Subcommand help is unchanged.

### Required options and arguments

Always-required CLI options and arguments must use Typer’s required sentinel (`typer.Option(...)` / `typer.Argument(...)`, or an equivalent with no default). Rich help then shows:

- a leading `*` in the options/arguments table (red)
- a trailing `[required]` on the help line (dim red)

Example:

```text
│ *  --role     -r      TEXT  Model role name. [required]                      │
│ *  --member           TEXT  Member UPN or Entra group display name …         │
│                             [required]                                       │
```

Do **not** fake this with a `None` default plus `(required)` in the help string — that skips the `*` column and looks inconsistent next to true required flags. When a flag is always required via `...`, omit a redundant `(required)` prefix — Typer already appends `[required]`.

**Conditionally required** flags (e.g. `--origin` / `--target` that are optional when `-m` / `-d` supply enough context) keep a `None` default. Mark them in help prose as `(required without -m or -d)` (or the accurate condition) via `conditional_required_help` in `fabric_tools.cli.options`. Do not use `...` for those — Click would reject otherwise-valid invocations.

**Optional** flags use plain help prose with no `(optional)` prefix — unmarked help means optional. Build strings with `option_help` in `fabric_tools.cli.options` (pass `when=` for a mode scope such as `deploy only` or `create only`, which renders as `(deploy only) …`).

### Activity spinner (busy / status)

Long-running work uses a Rich dots spinner on stderr (`fabric_tools.status.busy` / `update`). Every status line must use:

```text
<module>: <action> (<name>)…
```

- **module** — CLI command group (`notebook`, `semantic-model`, `inspect`, `setup`, `auth`, …)
- **action** — lowercase verb phrase (`downloading`, `adding role member`, `authenticating`)
- **name** — optional **display name** in parentheses; omit the ` (…)` segment when there is no name. Resolve via `item_display_name` / `status_item_label` (or kind-specific helpers) before calling `status_detail` — do not pass a raw item GUID. Short GUID truncation is only a fallback when lookup fails.

Examples:

```text
auth: authenticating…
notebook: downloading…
1 of 4 · notebook: downloading (Sales)…
semantic-model: adding role member (Harvest)…
inspect: listing workspaces…
setup: checking for updates…
```

Build lines with `status_detail(module, action, name=None)` (and `progress_message` for `n of m ·` prefixes). Do not put only a name after the module (e.g. `XMLA: Harvest…`); the action is required.

While a Fabric long-running operation (HTTP 202) is polled, a numeric `percentComplete` is appended after the trailing `…` (e.g. `1 of 4 · notebook: downloading (Sales)… 40%`) via `status.set_percent`. It is display-only (`current_message` is unchanged), omitted when Fabric returns `null`, cleared when polling ends, and never printed on non-TTY.

The dots spinner glyph is **green**; the status text stays primary (default). Do not append long hints onto the spinner line (auth stays `auth: authenticating (Windows)…` — device-code URI/user code print as a separate stderr line).

Nested `busy` / auth announcements may rewrite the same spinner; keep the same format. Clear the spinner (`status.clear`) before Error/Warning panels so they are not printed mid-line. For **non-blocking** notices that must stay visible while work continues, use `status.set_aside(renderable)` / `status.warn_aside(message)` — these draw under the live spinner without stopping it (replacing any prior aside). `status.clear_aside()` removes the aside. Outside `busy`, `set_aside` / `warn_aside` print once to stderr.

Stopping a spinner must not leave a blank line and must not cursor-up into the previous prompt (use in-place erase, not Rich `restore_cursor`). Live must not redirect stdout/stderr, or prompts get swallowed into the spinner.

**Never prompt under a live spinner.** Any yes/no prompt must run outside `busy`, or call `status.clear()` first — otherwise the spinner refresh erases the prompt and the CLI appears to hang while waiting on stdin. Do interactive pre-checks (e.g. SqlServer install offer) before entering a spinner.

**Yes/no prompts:** use `confirm.prompt_confirm` / `confirm.confirm_or_abort` (not raw `typer.confirm`). Decline and Ctrl+C/EOF both become a user abort: `ConfirmationAborted` + Warning panel `Aborted by user.`, never a red `Operation failed.` glued to `[y/N]:`. Sync exits go through `_exit_user_abort` so a stray `typer.Abort` is handled the same way.

XMLA role ops update the same spinner across stages (`connecting via XMLA` → `loading model` → `adding role member` / `saving model changes`, etc.) via stderr progress markers from `xmla_role_members.ps1`.

### Visual swatch

`fabric-tools debug color` (hidden from root `--help`) prints a two-column swatch using the same alignment as key/value rows: **right-aligned** colour name (in that style), then **left-aligned** primary text describing the role. A single `dim` row covers muted hints and secondary columns/keys. Use it to review terminal rendering after palette changes.

### Out of scope (for now)

- Colouring unified-diff `+/-` lines
- Non-CLI surfaces (future TUI)
