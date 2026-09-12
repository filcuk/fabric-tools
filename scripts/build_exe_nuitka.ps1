# Build fabric-tools with Nuitka (standalone + onefile) for A/B vs PyInstaller.
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_exe_nuitka.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_exe_nuitka.ps1 -StandaloneOnly
#
# Outputs under dist\nuitka\:
#   fabric-tools.dist\fabric-tools.exe  (standalone — fast layout / install source)
#   fabric-tools.exe                    (onefile — portable download)

param(
    [switch]$StandaloneOnly,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = "python"
$PythonArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
    $PythonArgs = @("-3")
}

Write-Host "Installing project with build extras (includes Nuitka)..."
& $Python @PythonArgs -m pip install -e ".[build]" -q
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed with exit code $LASTEXITCODE"
}

$OutputDir = Join-Path $RepoRoot "dist\nuitka"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

function Invoke-NuitkaBuild {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("standalone", "onefile")]
        [string]$Mode
    )

    Write-Host "Building Nuitka $Mode..."
    $CmdArgs = & $Python @PythonArgs -c @"
from pathlib import Path
import sys
sys.path.insert(0, r'$RepoRoot\packaging')
from nuitka_options import nuitka_command
print('\n'.join(nuitka_command(Path(r'$RepoRoot'), mode='$Mode', output_dir=Path(r'$OutputDir'))))
"@
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to resolve Nuitka $Mode arguments"
    }

    $ArgList = @($CmdArgs -split "`n" | Where-Object { $_ -ne "" })
    & $Python @PythonArgs @ArgList
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka $Mode build failed with exit code $LASTEXITCODE"
    }
}

Invoke-NuitkaBuild -Mode "standalone"

$StandaloneDir = Join-Path $OutputDir "fabric-tools.dist"
$StandaloneExe = Join-Path $StandaloneDir "fabric-tools.exe"
if (-not (Test-Path $StandaloneExe)) {
    throw "Expected standalone output not found: $StandaloneExe"
}

if (-not $SkipSmoke) {
    Write-Host "Smoke-testing standalone --help..."
    & $StandaloneExe --help
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka standalone --help failed with exit code $LASTEXITCODE"
    }
}

if (-not $StandaloneOnly) {
    Invoke-NuitkaBuild -Mode "onefile"

    $OnefileExe = Join-Path $OutputDir "fabric-tools.exe"
    if (-not (Test-Path $OnefileExe)) {
        throw "Expected onefile output not found: $OnefileExe"
    }

    if (-not $SkipSmoke) {
        Write-Host "Smoke-testing onefile --help..."
        & $OnefileExe --help
        if ($LASTEXITCODE -ne 0) {
            throw "Nuitka onefile --help failed with exit code $LASTEXITCODE"
        }
    }
}

Write-Host ""
Write-Host "Nuitka build succeeded."
Write-Host "  Standalone: $StandaloneExe"
if (-not $StandaloneOnly) {
    Write-Host "  Onefile:    $(Join-Path $OutputDir 'fabric-tools.exe')"
}
Write-Host "PyInstaller baseline remains: scripts\build_exe.ps1 -> dist\fabric-tools.exe"
Write-Host "Next: scripts\bench_startup.ps1 (after step 3) to compare cold starts."
