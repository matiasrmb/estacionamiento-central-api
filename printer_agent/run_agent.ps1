# printer_agent\run_agent.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "== Estacionamiento Central - Printer Agent =="

# Asegura que el working dir sea la raíz del repo
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
Write-Host "RepoRoot:" (Get-Location).Path

# Activar venv
if (!(Test-Path ".\.venv\Scripts\Activate.ps1")) {
  throw "No existe .\.venv\Scripts\Activate.ps1. Estás en la carpeta correcta?"
}
.\.venv\Scripts\Activate.ps1
Write-Host "Venv activado."

# Cargar .env a variables de entorno del proceso
$envPath = Join-Path $repoRoot ".env"
if (!(Test-Path $envPath)) {
  throw "No existe .env en la raíz del repo. Crea .env o verifica ubicación."
}

Get-Content $envPath | ForEach-Object {
  $line = $_.Trim()
  if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
    $parts = $line.Split("=", 2)
    $k = $parts[0].Trim()
    $v = $parts[1].Trim()
    # Quitar comillas si existen
    if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length-2) }
    if ($v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length-2) }
    [Environment]::SetEnvironmentVariable($k, $v, "Process")
  }
}

Write-Host "ENV PRINTER_NAME =" $env:PRINTER_NAME

if ([string]::IsNullOrWhiteSpace($env:PRINTER_NAME)) {
  throw "PRINTER_NAME está vacío. Edita .env y pon el nombre EXACTO de la impresora."
}

Write-Host "Iniciando agente..."
python -m printer_agent.agent

Write-Host "Agente finalizó."
Pause
