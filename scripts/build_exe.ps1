# Build the Windows release executable for fabric-tools (Nuitka onefile).
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
#
# Prefers Python 3.12 when available (MinGW works; 3.13+ requires MSVC).
#
# Final artifact:
#   dist\fabric-tools.exe
#
# Intermediate Nuitka output stays under dist\nuitka\ (not for distribution).

param(
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = "python"
$PythonArgs = @()
# Prefer 3.12 for Nuitka: --mingw64 is rejected on 3.13+.
if (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
    $Py312 = & py -3.12 -c "import sys; print(sys.version)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $Py312) {
        $PythonArgs = @("-3.12")
        Write-Host "Using Python 3.12 for Nuitka (MinGW-compatible)."
    }
    else {
        $PythonArgs = @("-3")
        Write-Host "Using default Python 3.x for Nuitka (3.13+ needs MSVC)."
    }
}

Write-Host "Installing project with build extras (includes Nuitka)..."
& $Python @PythonArgs -m pip install -e ".[build]" -q
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed with exit code $LASTEXITCODE"
}

$DistDir = Join-Path $RepoRoot "dist"
$OutputDir = Join-Path $DistDir "nuitka"
$PublishOnefile = Join-Path $DistDir "fabric-tools.exe"
$StaleStandalonePublish = Join-Path $DistDir "fabric-tools"
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

$BuildTimer = [System.Diagnostics.Stopwatch]::StartNew()

# --mode=onefile already performs a standalone build internally, then packs it.
Invoke-NuitkaBuild -Mode "onefile"

$OnefileSource = Join-Path $OutputDir "fabric-tools.exe"
if (-not (Test-Path $OnefileSource)) {
    throw "Expected onefile output not found: $OnefileSource"
}

$BuildTimer.Stop()
Write-Host ("Build duration: {0:hh\:mm\:ss\.fff} ({1:N1}s)" -f $BuildTimer.Elapsed, $BuildTimer.Elapsed.TotalSeconds)

Write-Host "Publishing single exe to dist\fabric-tools.exe..."
Copy-Item -LiteralPath $OnefileSource -Destination $PublishOnefile -Force

# Remove multi-file trees that are not for distribution.
if (Test-Path $StaleStandalonePublish) {
    Remove-Item -LiteralPath $StaleStandalonePublish -Recurse -Force
}
foreach ($bak in @(
        "$PublishOnefile.previous.bak",
        "$PublishOnefile.nuitka-orphan.bak"
    )) {
    if (Test-Path $bak) {
        Remove-Item -LiteralPath $bak -Force
    }
}

if (-not $SkipSmoke) {
    Write-Host "Smoke-testing onefile --help..."
    & $PublishOnefile --help
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka onefile --help failed with exit code $LASTEXITCODE"
    }

    Write-Host "Smoke-testing onefile setup status..."
    & $PublishOnefile setup status
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka onefile setup status failed with exit code $LASTEXITCODE"
    }
}

Write-Host ""
Write-Host "Nuitka onefile build succeeded." -ForegroundColor Green
Write-Host "Final artifact: $PublishOnefile" -ForegroundColor Green
Write-Host "Distribute that single exe. Portable runs extract on each launch;"
Write-Host "  .\dist\fabric-tools.exe setup install"
Write-Host "copies a fast unpacked tree under %LOCALAPPDATA%\fabric-tools\app"
Write-Host "Intermediate build tree (not for distribution): $OutputDir"
