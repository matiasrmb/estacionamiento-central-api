param(
    [string]$SpecPath = (Join-Path $PSScriptRoot "EstacionamientoCentralAPI.spec"),
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$python = Get-Command "python.exe" -ErrorAction SilentlyContinue
if (-not $python) {
    throw "python.exe was not found on PATH. Install Python 3 or run from the API development environment."
}

& $python.Source -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    & $python.Source -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install PyInstaller."
    }
}

$arguments = @("-m", "PyInstaller", $SpecPath, "--noconfirm")
if ($Clean) {
    $arguments += "--clean"
}

& $python.Source @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$outputDirectory = Join-Path $PSScriptRoot "dist\EstacionamientoCentralAPI"
$exePaths = @(
    (Join-Path $outputDirectory "EstacionamientoCentralAPI.exe"),
    (Join-Path $outputDirectory "EstacionamientoCentralSchemaMigrations.exe")
)
foreach ($exePath in $exePaths) {
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Expected packaged executable was not produced: $exePath"
    }
}

Write-Host "Packaged API executables ready: $($exePaths -join ', ')"
