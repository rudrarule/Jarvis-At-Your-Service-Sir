param(
    [string[]]$PytestArgs = @(
        "backend\test_mission_mode.py",
        "backend\test_langgraph_routing.py",
        "-q"
    ),
    [string]$DependencyTarget = "C:\tmp\jarvis-test-deps"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BundledPython = "C:\Users\Rudra\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $BundledPython)) {
    throw "Bundled Python was not found at $BundledPython"
}

$pathParts = @(
    $DependencyTarget,
    (Join-Path $RepoRoot "backend"),
    $RepoRoot,
    $env:PYTHONPATH
) | Where-Object { $_ -and $_.Trim() }

$env:PYTHONPATH = ($pathParts -join ";")

& $BundledPython -m pytest @PytestArgs
exit $LASTEXITCODE
