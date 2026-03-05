@echo off
setlocal

REM Ir a la raíz del repo para asegurar rutas correctas
cd /d C:\Users\matia\estacionamiento-central-api

REM Ejecutar PowerShell con flags compatibles con Windows PowerShell 5.1
REM Redirigir stdout/stderr a logs para diagnóstico
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\matia\estacionamiento-central-api\printer_agent\run_agent_forever.ps1" >> "C:\Users\matia\estacionamiento-central-api\printer_agent\logs\task_stdout.log" 2>> "C:\Users\matia\estacionamiento-central-api\printer_agent\logs\task_stderr.log"

endlocal