# Build a one-dir Windows console executable for fabric-tools.
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
#
# PyInstaller writes dist\fabric-tools\{exe,_internal}; this script flattens to
# dist\fabric-tools.exe + dist\_internal\ so the layout matches a release zip.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = "python"
$PythonArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
    $PythonArgs = @("-3")
}

Write-Host "Installing project with build extras..."
& $Python @PythonArgs -m pip install -e ".[build]" -q
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed with exit code $LASTEXITCODE"
}

Write-Host "Running PyInstaller..."
& $Python @PythonArgs -m PyInstaller --noconfirm --clean "packaging\fabric-tools.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$NestedDir = Join-Path $RepoRoot "dist\fabric-tools"
$NestedExe = Join-Path $NestedDir "fabric-tools.exe"
if (-not (Test-Path $NestedExe)) {
    throw "Expected output not found: $NestedExe"
}

$DistDir = Join-Path $RepoRoot "dist"
$ExePath = Join-Path $DistDir "fabric-tools.exe"
$InternalDir = Join-Path $DistDir "_internal"

Write-Host "Flattening onedir layout into dist\ ..."
# Remove a previous flat install so Move-Item cannot collide with leftovers.
if (Test-Path $ExePath) {
    Remove-Item -LiteralPath $ExePath -Force
}
if (Test-Path $InternalDir) {
    Remove-Item -LiteralPath $InternalDir -Recurse -Force
}
Get-ChildItem -LiteralPath $NestedDir | ForEach-Object {
    Move-Item -LiteralPath $_.FullName -Destination $DistDir -Force
}
Remove-Item -LiteralPath $NestedDir -Recurse -Force

if (-not (Test-Path $ExePath) -or -not (Test-Path $InternalDir)) {
    throw "Flatten failed; expected $ExePath and $InternalDir"
}

Write-Host "Smoke-testing executable --help..."
& $ExePath --help
if ($LASTEXITCODE -ne 0) {
    throw "fabric-tools.exe --help failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Build succeeded: $ExePath"
Write-Host "Distribute dist\fabric-tools.exe together with dist\_internal\ (e.g. zip those two)."
Write-Host "Note: unsigned binaries may trigger SmartScreen warnings."
Write-Host "Auth still uses interactive browser/device-code or AZURE_* service principal env vars."
