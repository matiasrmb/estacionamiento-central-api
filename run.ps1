# run.ps1 - Arranque local para estacionamiento-central-api

$ErrorActionPreference = "Stop"

# Ir a la carpeta raíz del proyecto (donde está este script)
Set-Location -Path $PSScriptRoot

Write-Host "Proyecto:" (Get-Location)

function Get-LanIPv4Address {
  $activeInterfaces = Get-NetIPInterface -AddressFamily IPv4 |
    Where-Object { $_.ConnectionState -eq "Connected" } |
    Select-Object -ExpandProperty InterfaceIndex

  $preferred = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*" -and
      $_.AddressState -eq "Preferred" -and
      $activeInterfaces -contains $_.InterfaceIndex
    } |
    Sort-Object @{ Expression = { if ($_.InterfaceAlias -match "Wi-Fi|Wireless|WLAN") { 0 } else { 1 } } }, InterfaceMetric |
    Select-Object -First 1

  if (-not $preferred) {
    $preferred = Get-NetIPAddress -AddressFamily IPv4 |
      Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.AddressState -eq "Preferred"
      } |
      Sort-Object @{ Expression = { if ($_.InterfaceAlias -match "Wi-Fi|Wireless|WLAN") { 0 } else { 1 } } } |
      Select-Object -First 1
  }

  if (-not $preferred) {
    throw "No se pudo detectar una IP LAN activa. Verifica que estés conectado a una red."
  }

  return $preferred.IPAddress
}

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

# 3) Detectar URL LAN y generar QR de conexión para la app mobile
$port = if ($env:API_PORT) { [int]$env:API_PORT } else { 8000 }
$lanIp = Get-LanIPv4Address
$apiBaseUrl = "http://$($lanIp):$($port)/api/v1"
$qrPath = Join-Path $PSScriptRoot "connect_api_qr.png"

Write-Host ""
Write-Host "==============================================="
Write-Host " URL para conectar la app mobile:"
Write-Host " $apiBaseUrl"
Write-Host ""
Write-Host " Si la Sunmi no puede escanear QR, ingresa manualmente:"
Write-Host " IP:     $lanIp"
Write-Host " Puerto: $port"
Write-Host "==============================================="
Write-Host ""

$qrScript = @'
import sys

url = sys.argv[1]
path = sys.argv[2]

try:
    import qrcode
except Exception:
    import subprocess
    print("Instalando dependencia para generar QR: qrcode[pil] ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "qrcode[pil]"])
    import qrcode

qr = qrcode.QRCode(border=2)
qr.add_data(url)
qr.make(fit=True)
qr.print_ascii(invert=True)
img = qr.make_image(fill_color="black", back_color="white")
img.save(path)
print(f"QR guardado en: {path}")
'@

$qrScriptPath = Join-Path $env:TEMP "estacionamiento_api_qr.py"
Set-Content -Path $qrScriptPath -Value $qrScript -Encoding UTF8
python $qrScriptPath $apiBaseUrl $qrPath

if (Test-Path $qrPath) {
  Start-Process $qrPath
}

# 4) Levantar API
Write-Host ""
Write-Host "Iniciando API en 0.0.0.0:$port ..."
uvicorn app.main:app --host 0.0.0.0 --port $port --reload
