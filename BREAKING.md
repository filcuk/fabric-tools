# BREAKING.md

## Unreleased

- Download: remote is `-o`, optional local path is `-t` (was `-t` remote / `-f` path)
- Deploy / compare: local path is `-o` (was `-f`); remote target stays `-t`
- `--file` / `-f` for paths removed; `-f` is only `--filter`
- Inspect type filter: `--artifact` / `-a` (was `--item` / `-i`)
