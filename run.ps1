# run.ps1 - Arranque local para estacionamiento-central-api

$ErrorActionPreference = "Stop"

# Ir a la carpeta raíz del proyecto (donde está este script)
Set-Location -Path $PSScriptRoot

Write-Host "Proyecto:" (Get-Location)

# 1) Activar entorno virtual
$activate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
  throw "No se encontró el activador del venv en: $activate. ¿Creaste el venv en .venv?"
}

Write-Host "Activando venv..."
& $activate

# 2) Cargar variables desde .env (si existe)
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
  Write-Host "Cargando .env..."
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
      $k, $v = $line.Split("=", 2)
      $k = $k.Trim()
      $v = $v.Trim().Trim('"').Trim("'")
      [System.Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
  }
} else {
  Write-Host "No existe .env (ok)."
}

# 3) Levantar API
Write-Host "Iniciando API..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload