# printer_agent\run_agent_forever.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$taskLog   = Join-Path $logDir "print_agent_task.log"
$stdoutLog = Join-Path $logDir "print_agent_stdout.log"
$stderrLog = Join-Path $logDir "print_agent_stderr.log"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Out-File -FilePath $taskLog -Append -Encoding UTF8
}

Log "=== START run_agent_forever ==="
Log "RepoRoot: $repoRoot"
Log "User: $env:USERNAME"
Log "PWD: $((Get-Location).Path)"

# --- Single instance guard (lock file) ---
$lockFile = Join-Path $logDir "print_agent.lock"

if (Test-Path $lockFile) {
    try {
        $existingPid = Get-Content $lockFile -ErrorAction Stop
        if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
            Log "Otra instancia ya está corriendo. PID=$existingPid. Saliendo."
            exit 0
        }
    } catch {
        # lock corrupto: continuar
    }
}

$PID | Out-File -FilePath $lockFile -Encoding ASCII -Force
Log "Lock adquirido. PID=$PID"
# --- end guard ---

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (!(Test-Path $venvPython)) {
    Log "ERROR: python venv not found at $venvPython"
    throw "No existe .venv\Scripts\python.exe en $repoRoot"
}

$envPath = Join-Path $repoRoot ".env"
if (!(Test-Path $envPath)) {
    Log "ERROR: .env not found at $envPath"
    throw "No existe .env en $repoRoot"
}

# Cargar .env una sola vez al proceso del launcher
Get-Content $envPath | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $parts = $line.Split("=", 2)
        $k = $parts[0].Trim()
        $v = $parts[1].Trim()
        if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length-2) }
        if ($v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length-2) }
        [Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}

Log "ENV PRINTER_NAME=$env:PRINTER_NAME"
Log "ENV ACROBAT_PATH=$env:ACROBAT_PATH"

function Wait-SpoolerAndPrinter([string]$printerName, [int]$timeoutSeconds = 90) {
    Log "Preflight: esperando Spooler + impresora '$printerName' (timeout ${timeoutSeconds}s)..."

    $deadline = (Get-Date).AddSeconds($timeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        try {
            $spooler = Get-Service -Name Spooler -ErrorAction Stop
            if ($spooler.Status -ne 'Running') {
                Log "Preflight: Spooler status=$($spooler.Status). Intentando iniciar..."
                Start-Service -Name Spooler -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
                continue
            }

            $p = Get-Printer -Name $printerName -ErrorAction SilentlyContinue
            if ($null -ne $p) {
                Log "Preflight OK: impresora encontrada. Name='$($p.Name)' Status='$($p.PrinterStatus)'"
                return $true
            } else {
                Log "Preflight: impresora aún no disponible. Reintentando..."
            }
        } catch {
            Log "Preflight EXCEPTION: $($_.Exception.Message)"
        }

        Start-Sleep -Seconds 5
    }

    Log "Preflight FAIL: timeout. No se detectó impresora '$printerName'."
    return $false
}

# Delay inicial (evita condición de carrera post-boot)
Start-Sleep -Seconds 10

if (-not (Wait-SpoolerAndPrinter -printerName $env:PRINTER_NAME -timeoutSeconds 90)) {
    # No abortamos para siempre: dejamos que el loop relance,
    # pero así evitamos que arranque agente cuando el sistema no está listo.
    Log "No se pudo validar impresora/spooler. Se seguirá reintentando en el loop."
}

if ([string]::IsNullOrWhiteSpace($env:PRINTER_NAME)) {
    throw "PRINTER_NAME vacío. Edita .env y define nombre exacto de impresora."
}

try {
    while ($true) {
        try {
            Log "Lanzando agente como proceso separado..."

            $p = Start-Process `
                -FilePath $venvPython `
                -ArgumentList "-m printer_agent.agent" `
                -WorkingDirectory $repoRoot `
                -NoNewWindow `
                -RedirectStandardOutput $stdoutLog `
                -RedirectStandardError $stderrLog `
                -PassThru

            Log "Agente iniciado. PID=$($p.Id). Esperando salida..."
            $p.WaitForExit()

            Log "Agente terminó (inesperado). ExitCode=$($p.ExitCode)"
        }
        catch {
            Log "EXCEPTION: $($_.Exception.Message)"
            Log "STACK: $($_.ScriptStackTrace)"
        }

        Log "Reintentando en 5 segundos..."
        Start-Sleep -Seconds 5
    }
}
finally {
    if (Test-Path $lockFile) { Remove-Item $lockFile -Force -ErrorAction SilentlyContinue }
    Log "Launcher finalizado. Lock liberado."
}