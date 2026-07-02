param(
    [switch]$Clean
)

$script = Join-Path $PSScriptRoot "build_api_exe.ps1"
& $script -Clean:$Clean
exit $LASTEXITCODE
