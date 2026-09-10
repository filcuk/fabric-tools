# Build the Windows release executable for fabric-tools.
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
#
# 1) Build onedir (staging) to get a thin bootloader + _internal
# 2) Build onefile release that embeds that bootloader for `setup install`
# Ship: dist\fabric-tools.exe (portable as-is; setup install unpacks to a fast onedir)

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

Write-Host "Building onedir staging (bootloader + _internal)..."
& $Python @PythonArgs -m PyInstaller --noconfirm --clean "packaging\fabric-tools.spec"
if ($LASTEXITCODE -ne 0) {
    throw "Onedir PyInstaller failed with exit code $LASTEXITCODE"
}

$OnedirDir = Join-Path $RepoRoot "dist\fabric-tools"
$OnedirExe = Join-Path $OnedirDir "fabric-tools.exe"
if (-not (Test-Path $OnedirExe)) {
    throw "Expected onedir output not found: $OnedirExe"
}

Write-Host "Building onefile release (embeds onedir bootloader)..."
$env:FABRIC_TOOLS_ONEDIR_BOOTLOADER = $OnedirExe
try {
    & $Python @PythonArgs -m PyInstaller --noconfirm --clean "packaging\fabric-tools-onefile.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "Onefile PyInstaller failed with exit code $LASTEXITCODE"
    }
}
finally {
    Remove-Item Env:FABRIC_TOOLS_ONEDIR_BOOTLOADER -ErrorAction SilentlyContinue
}

$DistDir = Join-Path $RepoRoot "dist"
$ExePath = Join-Path $DistDir "fabric-tools.exe"
if (-not (Test-Path $ExePath)) {
    throw "Expected onefile output not found: $ExePath"
}

# Drop staging onedir from dist so the release artifact is a single exe.
if (Test-Path $OnedirDir) {
    Remove-Item -LiteralPath $OnedirDir -Recurse -Force
}
$StaleInternal = Join-Path $DistDir "_internal"
if (Test-Path $StaleInternal) {
    Remove-Item -LiteralPath $StaleInternal -Recurse -Force
}

Write-Host "Smoke-testing onefile --help..."
& $ExePath --help
if ($LASTEXITCODE -ne 0) {
    throw "fabric-tools.exe --help failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Build succeeded: $ExePath"
Write-Host "Distribute that single exe. Users can run it portable, or:"
Write-Host "  .\fabric-tools.exe setup install"
Write-Host "to unpack a fast onedir copy under %LOCALAPPDATA%\fabric-tools\app"
Write-Host "Note: unsigned binaries may trigger SmartScreen warnings."
Write-Host "Auth still uses interactive browser/device-code or AZURE_* service principal env vars."
