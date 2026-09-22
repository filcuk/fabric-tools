# Development

Contributor guide for `fabric-tools`. End-user CLI usage lives in [README.md](README.md). Agent-oriented project notes live in [AGENTS.md](AGENTS.md). CLI colour and layout design live in [DESIGN.md](DESIGN.md).

## Requirements

- Python 3.11+ (`py -3` on Windows if `python` points at an older runtime)
- Access to a Microsoft Fabric tenant (for live API operations)

## Install

From the repo root:

```bash
py -3 -m pip install -e ".[dev]"
```

Optional extras:

- `.[dev]` — pytest, Ruff, and test helpers
- `.[build]` — Nuitka for Windows executable builds

## Run from Python

```bash
py -3 -m fabric_tools --version
py -3 -m fabric_tools --help
py -3 -m fabric_tools inspect --help
py -3 -m fabric_tools notebook --help
py -3 -m fabric_tools pipeline --help
py -3 -m fabric_tools udf --help
py -3 -m fabric_tools --interactive
```

If Scripts is on your PATH after install, `fabric-tools` works the same way.

Examples match the user docs in [README.md](README.md); swap `.\fabric-tools.exe` for `py -3 -m fabric_tools` (or `fabric-tools`) while developing.

To register the current Python-based CLI for your user account (creates a `.cmd` shim under `%LOCALAPPDATA%\fabric-tools\app`):

```bash
py -3 -m fabric_tools setup install
```

## Lint and format

Uses [Ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`):

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m ruff check .
py -3 -m ruff format --check .
```

To apply fixes and reformat:

```bash
py -3 -m ruff check --fix .
py -3 -m ruff format .
```

## Tests

```bash
py -3 -m pip install -e ".[dev]"
py -3 -m pytest
```

Covered areas: parsing/pairing, definition pack/unpack, LRO client (mocked HTTP), download/deploy ops, compare diffs, dry-run validation, interactive wizard dispatch.

## Build Windows executable

Produces a single portable `dist/fabric-tools.exe` via **Nuitka onefile**. Prefer **Python 3.12** for the build (`py -3.12`); 3.13+ needs MSVC instead of MinGW.

`setup install` unpacks to a fast tree under `%LOCALAPPDATA%\fabric-tools\app`.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
.\dist\fabric-tools.exe --help
```

Notes:

- Packaging: [`packaging/nuitka_options.py`](packaging/nuitka_options.py), [`packaging/nuitka_entry.py`](packaging/nuitka_entry.py)
- Ship only `dist/fabric-tools.exe`. Do not distribute `dist/nuitka/` intermediates (`.dist` / `.build`)
- Portable runs extract under `%LOCALAPPDATA%\fabric-tools\cache\`; `setup install` copies to `app\` and clears the cache
- Do not commit `dist/` or `build/`
- Unsigned binaries may trigger SmartScreen warnings
- Auth from the exe uses Windows WAM (when available), browser/device-code, or `AZURE_*` service principal env vars; tokens persist under `%LOCALAPPDATA%\fabric-tools`

## Point the `latest` tag

The install docs use a fixed download URL keyed by the `latest` git tag (`…/releases/download/latest/fabric-tools.exe`). After publishing a version tag (for example `v0.6.0`), repoint `latest` to the same commit and force-push the tag:

```powershell
git tag -f latest v0.6.0
git push origin refs/tags/latest --force
```

Verify both refs match:

```powershell
git rev-parse latest v0.6.0
```

Anyone who already fetched the old `latest` should re-fetch with `git fetch --tags --force`.

## XMLA role membership (SqlServer / PowerShell Gallery)

Product commands: `fabric-tools semantic-model role list|member add|member remove`.

**Backend:** Windows `pwsh` (preferred) or Windows PowerShell 5.1 + **SqlServer** module from PSGallery (Analysis Services / TOM). Not a bundled native helper. REST dataset permissions are not RLS role members.

**Module check:** the CLI runs `ensure_sqlserver_module` **once, up front** (before auth/confirm, outside any spinner). If SqlServer is missing it prompts `Install from PSGallery for CurrentUser now?` (or fails immediately with the install hint under `-s`). Never prompt under a live spinner — the prompt is erased on the next refresh and looks like a hang. The install itself runs under its own spinner with a long timeout (it can take minutes). Note `find_powershell` prefers `pwsh` — the module must be installed for the host that is actually used.

**Script:** shipped as `fabric_tools/xmla_role_members.ps1` (also [`scripts/xmla_role_members.ps1`](scripts/xmla_role_members.ps1) in the repo). Override with `FABRIC_TOOLS_XMLA_SCRIPT`. Token on stdin JSON only. Connect timeout defaults to 15s (`FABRIC_TOOLS_XMLA_CONNECT_TIMEOUT`); the Python runner kills the PowerShell process tree after connect+5s (≤ overall `FABRIC_TOOLS_XMLA_TIMEOUT`, default 25s) because AMO often ignores `Connect Timeout`. An external `Stop-Process` killer backs that up inside the script. Stage markers on stderr drive the spinner; failures include the stage and data-source URL.

**Personal workspace (My workspace):** XMLA requires the v2 URL `powerbi://api.powerbi.com/v2.0/{tenantId}/home/myworkspace/{UPN|oid}` (not `v1.0/myorg/My workspace`, which hangs in client libraries). fabric-tools builds this from workspace `type: Personal` / display name and the signed-in token claims (object id preferred). **The workspace must also have a `capacityId`** (Premium / PPU / Fabric with XMLA read/write). fabric-tools checks `capacityId` up front — a personal workspace with no capacity fails immediately with `xmla_capacity_required` instead of AMO's opaque `Authentication failed for all authenticators`. Role existence is only checked after a successful connect.

```powershell
py -3 -m fabric_tools semantic-model role --help
py -3 -m fabric_tools semantic-model role list -t <workspaceId>:<semanticModelId>
py -3 -m fabric_tools semantic-model role member add -t <workspaceId>:* -f Sales -r Readers --member user@contoso.com
```

If SqlServer is missing, the CLI offers `Install-Module SqlServer -Scope CurrentUser` (confirm required). `-s` / `--silent` skips the offer (and confirms on member mutations).

**Live-trial notes:**

- Capacity / workspace must allow **XMLA read/write**
- Power BI API scope token (CLI acquires this for role commands)
- Members are UPNs or Entra groups; service principals are not valid RLS role members
- Add/remove are idempotent (`changed: false` when already present / absent)
- Prefer PowerShell 7 (`pwsh`) when available; 5.1 works with a current SqlServer module
- Hidden `debug xmla-roles` remains available for low-level probing
