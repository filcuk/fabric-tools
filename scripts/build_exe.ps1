# Build a one-file Windows console executable for fabric-tools.
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = "py"
$PythonArgs = @("-3")

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

$ExePath = Join-Path $RepoRoot "dist\fabric-tools.exe"
if (-not (Test-Path $ExePath)) {
    throw "Expected output not found: $ExePath"
}

Write-Host "Smoke-testing executable --help..."
& $ExePath --help
if ($LASTEXITCODE -ne 0) {
    throw "fabric-tools.exe --help failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Build succeeded: $ExePath"
Write-Host "Note: unsigned binaries may trigger SmartScreen warnings."
Write-Host "Auth still uses interactive browser/device-code or AZURE_* service principal env vars."
