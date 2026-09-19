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

## Global / common

| Long | Short | Scope | Meaning |
|------|-------|--------|---------|
| `--help` | `-h` | everywhere | Show help |
| `--version` | `-v` | root | Show version |
| `--interactive` | `-i` | root | Guided wizard |
| `--manifest` | `-m` | sync / pack / manifest cmds | `.ftdep` stem or path |
| `--silent` | `-s` | mutating cmds | Skip confirms |
| `--dry-run` | `-d` | sync / pack | Validate only |
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

## Removed (do not reintroduce)

| Former | Notes |
|--------|--------|
| `--file` / `-f` (as path) | Paths are `--origin` or `--target` by mode; `-f` is `--filter` only |
| `--item` / `-i` (inspect) | Replaced by `--artifact` / `-a` |
