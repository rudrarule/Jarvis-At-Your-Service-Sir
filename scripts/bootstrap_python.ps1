param(
    [string]$DependencyTarget = "C:\tmp\jarvis-test-deps",
    [switch]$InstallBackendRequirements
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BundledPython = "C:\Users\Rudra\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $BundledPython)) {
    throw "Bundled Python was not found at $BundledPython"
}

New-Item -ItemType Directory -Force -Path $DependencyTarget | Out-Null

& $BundledPython -m pip install --upgrade --target $DependencyTarget pytest pytest-asyncio
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed with exit code $LASTEXITCODE"
}

if ($InstallBackendRequirements) {
    $Requirements = Join-Path $RepoRoot "backend\requirements.txt"
    & $BundledPython -m pip install --upgrade --target $DependencyTarget -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "backend requirements install failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Python: $BundledPython"
Write-Host "Test dependencies: $DependencyTarget"
Write-Host "Backend requirements installed: $InstallBackendRequirements"
Write-Host "Run tests with: $RepoRoot\scripts\run_backend_tests.ps1"
