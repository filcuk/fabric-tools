# <img src="res/app.svg" alt="" width="40" height="40" align="left"> Fabric Tools

_CLI for working with Microsoft Fabric artifacts._
![Platform](https://img.shields.io/badge/platform-Windows-blue) ![GitHub Issues](https://img.shields.io/github/issues/filcuk/fabric-tools) ![GitHub Release](https://img.shields.io/github/v/release/filcuk/fabric-tools?include_prereleases)

_Video here later_

Have you ever wanted to:

- Work in your preferred IDE
- Push and compare code without using git
- Quickly update specific notebook cells
- Deploy items across multiple workspaces simultaneously
- Efficiently back up or remove large numbers of items
- Use alternative agents besides Copilot

[fabric-tools](https://github.com/filcuk/fabric-tools/) is made for ~~lazy~~ _efficient_ developers, intended to _streamline daily tasks_ across Fabric, avoiding clunky online editors and slow deployment pipelines.  

## Quick start

1. Download the [latest release](https://github.com/filcuk/fabric-tools/releases/download/v0.4.0/fabric-tools.exe)
2. _Optionally_ install for improved speed and ease of access:

  ```powershell
  .\fabric-tools.exe setup install
  ```

  _Restart your terminal or IDE to capture PATH change._
3. Keep up to date (downloads the release exe and installs over `%LOCALAPPDATA%\fabric-tools\app`; works from the installed exe or a Python install):

  ```powershell
  fabric-tools setup update --check
  fabric-tools setup update
  ```

4. See available commands or use interactive wizard to get started:

  ```powershell
  fabric-tools --help
  fabric-tools --interactive
  ```

> [!success]
> Are you working with agents? Use `fabric-tools env` to set `FABRIC_TOOLS_READONLY=1` to block any destructive commands.

## Example workflow

```powershell
# Find notebooks in project workspaces
fabric-tools inspect workspace list -f 'projects'
fabric-tools inspect item list -t <workspaceId> -t Notebook

# Download a notebook from Fabric and save a deployment manifest
fabric-tools notebook download -s -t <workspaceId>:<notebookId> -f .\etl.ipynb -m etl

# Compare and deploy a local notebook vs the remote Fabric version using the manifest
fabric-tools notebook compare -m etl
fabric-tools notebook deploy -m etl
```

## Support

| Item|One-way|Two-way|Notes|
|---|---|---|---|
| Notebook|✅|✅|Can update individual cells.|
| Dataflow Gen2|✅|✅|Opt-in `--publish` / `-p` after deploy (Apply Changes).|
| Dataflow Gen1|✅|🚫|Deploy is create-only[^1].|
| Data Pipeline|✅|✅||
| User Data Function|✅|✅||
| Semantic Model|✅|✅||
| Report|✅|✅|Standalone or model-joined operations.|
| Paginated Report|✅|✅|No API support for sources & credentials.|
| Org App|✅|✅|`definition.json` in a `*.OrgApp` folder.|
| Inspect|✅ (Read)|🚫|Browse workspaces and items.|
| Pack manifests|✅|✅|Schema v3 multi-kind `.ftdep`; `pack …` for mixed.|
| Environment|📅|📅||
| Variable Library|📅|📅||
| Lakehouse|🚫|🚫|No API support.|
| Warehouse|❔|❔||
| Eventhouse|❔|❔||
| Eventstream|❔|❔||
| KQL Database|❔|❔||
| KQL Queryset|❔|❔||
| KQL Dashboard|❔|❔||
| Reflex (Activator)|❔|❔||
| Mirrored Database|❔|❔||
| Ontology|❔|❔||

**Legend:**  
✅ = Supported  
📅 = Planned  
🚫 = Not supported  

[^1]: Dataflow Gen1 don't support overwrite, and credentials must be handled separately.

## Authentication

By default, interactive Azure sign-in is used, with Windows attempting silent account login first and falling back to browser or device code if needed.

For automation, set a service principal:

```powershell
$env:AZURE_TENANT_ID="..."
$env:AZURE_CLIENT_ID="..."
$env:AZURE_CLIENT_SECRET="..."

# or use the built-in env manager:
fabric-tools env -h
```

> [!warning]
> User Data Function APIs do **not** support service principals.

## Troubleshooting

### Indefinite authentication

If `Authenticating...` never finishes in Cursor / VS Code, the Windows account prompt is
probably not visible. The CLI should move on to browser sign-in after a short wait; you
can also run the same command in Windows Terminal. To drop a bad cached login:

### Corrupted credential

Remove bad cached auth record:

```powershell
Remove-Item "$env:LOCALAPPDATA\fabric-tools\msal-auth-record.json" -ErrorAction SilentlyContinue
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success, up to date |
| `1` | Validation error, user abort, compare found differences, or newer release available |
| `2` | API or operation failure, update check failure |

## License

See [LICENSE](LICENSE).
