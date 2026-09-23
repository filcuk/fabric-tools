# FLAGS.md

Living inventory of public CLI flags and short aliases. Update this file whenever
options change. Check it before introducing a new short letter or long name to
avoid conflicts.

See also [BREAKING.md](BREAKING.md) for migrations and [AGENTS.md](AGENTS.md) for
the short-alias matching rule.

## Short-alias rule

1. A short option letter must match its long option (primary word initial):
   `--origin`→`-o`, `--target`→`-t`, `--filter`→`-f`, `--artifact`→`-a`, etc.
2. A short option never means a different long option.
3. No hidden rename aliases (do not accept removed names as synonyms).
4. Within one command, one short flag maps to exactly one long flag.
5. Update this file in the same change that adds or renames a flag.

## Shared short letters

### `-i` (include / exclude family)

`-i` is shared across different long flags on **different** commands. That is
intentional: those flags are include/exclude (scope) modifiers:

| Long | Short | Scope |
|------|-------|--------|
| `--include-schedules` | `-i` | pipeline / pack |
| `--include-outputs` | `-i` | notebook compare |
| `--independent` | `-i` | report / semantic-model / pack (join opt-out) |
| `--interactive` | `-i` | root wizard entry |

New `-i` usages should stay in this include/exclude pattern. Inspect type filter
is **`--artifact` / `-a`**, not `-i`.

## Core sync endpoints (from → to)

| Long | Short | Meaning | Value shape |
|------|-------|---------|-------------|
| `--origin` | `-o` | Where content comes **from** | Local path **or** remote selector |
| `--target` | `-t` | Where content goes **to** / destination | Local path **or** remote selector (by mode) |
| `--filter` | `-f` | `displayName` substring | Text; inspect always; sync only with `workspaceId:*` |

Local artifact paths are stems: a bare name gets the kind extension automatically
(like `-m etl` → `etl.ftdep`), e.g. `-t .\myApp` → `myApp.OrgApp`, `-t .\ETL` → `ETL.ipynb`.
`-t` / `-o` name the artifact, not a parent dump folder. Explicit kind suffixes are unchanged.

Remote selector shapes: `workspaceId`, `workspaceId:itemId`, `workspaceId:*` (and bare-GUID shorthand
inside a CSV after a qualified `workspace:…` piece). Multiplicity: repeat flags and/or
comma-separated lists. Expand `*` after auth (Fabric `list_items` type filter, or Power BI
list APIs for gen1 / paginated reports); zero matches is an error. Manifests stay concrete
(no `*` / filters in `.ftdep`).

### Mode usage

| Mode | `--origin` / `-o` | `--target` / `-t` |
|------|-------------------|-------------------|
| download | required remote | optional local path |
| deploy | required local path or remote | required remote |
| compare | required local path or remote | required remote |
| delete | not used | required remote |
| run / refresh | not used | required remote (or `-m` with itemId) |

## Global / common

| Long | Short | Scope | Meaning |
|------|-------|--------|---------|
| `--help` | `-h` | everywhere | Show help |
| `--version` | `-v` | root | Show version |
| `--interactive` | `-i` | root | Guided wizard |
| `--manifest` | `-m` | sync / pack / manifest / run / refresh cmds | `.ftdep` stem or path |
| `--silent` | `-s` | mutating cmds | Skip confirms |
| `--dry-run` | `-d` | sync / pack / run / refresh | Validate only |
| `--no-wait` | `-w` | run / refresh | Return after the job is accepted; do not wait |
| `--name` | `-n` | create deploy | Display name |
| `--cells` | `-c` | notebook deploy | 1-based cell indices |
| `--remap` | `-r` | deploy (selected kinds) | GUID map JSON |
| `--publish` | `-p` | dataflow deploy | Apply Changes after deploy |

## Inspect

| Long | Short | Meaning |
|------|-------|---------|
| `--target` | `-t` | Workspace or `workspaceId:itemId` |
| `--filter` | `-f` | Case-insensitive `displayName` substring |
| `--artifact` | `-a` | Fabric type filter (`Notebook`, `Workspace`, …); maps to API `type` |

## Kind-specific include/exclude

| Long | Short | Scope |
|------|-------|--------|
| `--include-schedules` | `-i` | pipeline download/deploy/compare; pack |
| `--include-outputs` | `-i` | notebook compare |
| `--independent` | `-i` | report / semantic-model / pack |

## Run / refresh

`notebook run`, `pipeline run`, `dataflow refresh`, `semantic-model refresh`.

| Long | Short | Meaning |
|------|-------|---------|
| `--target` | `-t` | `workspaceId:itemId` or `workspaceId:*` (no `--origin`) |
| `--manifest` | `-m` | Load entries with `itemId`; never rewritten |
| `--filter` | `-f` | `displayName` substring; only with `workspaceId:*` |
| `--silent` | `-s` | Skip confirm |
| `--dry-run` | `-d` | Resolve targets only; start nothing |
| `--no-wait` | `-w` | Return after accept (default waits for completion) |

`-w` is the short form of `--no-wait` (primary word `wait`); there is no `--wait` flag.

## Semantic-model role (RLS members)

| Long | Short | Scope | Meaning |
|------|-------|--------|---------|
| `--target` | `-t` | `semantic-model role …` | `workspaceId:itemId` or `workspaceId:*` |
| `--filter` | `-f` | with `workspaceId:*` | `displayName` substring |
| `--role` | `-r` | `role member add\|remove` | Model role name (not deploy `--remap`) |
| `--member` | (none) | `role member add\|remove` | UPN or Entra group; `-m` stays `--manifest` elsewhere |
| `--silent` | `-s` | mutating / install offer | Skip confirms; no Install-Module prompt |
| `--dry-run` | `-d` | all role cmds | Resolve/plan only; no XMLA mutation |

Windows + SqlServer PSGallery module; XMLA read/write capacity required.

## Removed (do not reintroduce)

| Former | Notes |
|--------|--------|
| `--file` / `-f` (as path) | Paths are `--origin` or `--target` by mode; `-f` is `--filter` only |
| `--item` / `-i` (inspect) | Replaced by `--artifact` / `-a` |
