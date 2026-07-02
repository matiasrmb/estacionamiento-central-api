from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


SUPPORTED_PRINT_PATH = (
    "Supported print path: SumatraPDF + configured Windows PRINTER_NAME + "
    "validated vendor/thermal driver. Generic thermal drivers are not a "
    "supported reliability guarantee."
)


def build_print_diagnostics(
    *,
    sumatra_path: str,
    sumatra_exists: bool,
    printer_name: str,
    printers: list[dict[str, Any]],
    queue_count: int,
    last_error: str,
) -> dict[str, Any]:
    """Build non-destructive Print Agent diagnostics."""
    has_sumatra = bool(sumatra_path and sumatra_exists)
    configured = (printer_name or "").strip()
    matching_printer = next((p for p in printers if p.get("name") == configured), None)

    sumatra = {
        "status": "PASS" if has_sumatra else "FAIL",
        "path": sumatra_path,
        "message": "SumatraPDF executable found" if has_sumatra else "SUMATRA_PATH is missing or does not exist",
    }

    if not configured:
        printer_status = "FAIL"
        printer_message = "PRINTER_NAME is not configured"
    elif not matching_printer:
        printer_status = "WARN"
        printer_message = "PRINTER_NAME was not found in installed printers"
    elif matching_printer.get("offline"):
        printer_status = "WARN"
        printer_message = "Configured printer is offline"
    else:
        printer_status = "PASS"
        printer_message = "Configured printer is available"

    printer = {
        "status": printer_status,
        "name": configured,
        "message": printer_message,
        "queue_count": queue_count,
        "detected": matching_printer or {},
    }

    status = "PASS" if sumatra["status"] == "PASS" and printer["status"] == "PASS" else "FAIL"
    next_actions = (
        "Run a Windows test page, verify the vendor thermal driver, confirm "
        "PRINTER_NAME matches Windows exactly, then retry or save/reprint the PDF."
    )

    return {
        "status": status,
        "supported_path": SUPPORTED_PRINT_PATH,
        "sumatra": sumatra,
        "printer": printer,
        "last_error": last_error or "",
        "next_actions": next_actions,
    }


def build_test_print_guidance(*, pdf_path: str, printer_name: str) -> str:
    """Describe a safe manual test-print workflow without printing in tests."""
    return (
        f"Generar un ticket de prueba en {pdf_path} y enviarlo a {printer_name}. "
        "Este ticket de prueba no modifica caja, ingresos, salidas ni reportes. "
        "Si falla, guardar el PDF, ejecutar una página de prueba de Windows y "
        "validar el driver térmico antes de reintentar."
    )


def collect_windows_printers() -> list[dict[str, Any]]:
    """Return installed Windows printers using PowerShell, or [] when unavailable."""
    command = (
        "Get-Printer | Select-Object Name,WorkOffline,PrinterStatus,PortName "
        "| ConvertTo-Json -Depth 3"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        raw = json.loads(result.stdout)
        rows = raw if isinstance(raw, list) else [raw]
        return [
            {
                "name": row.get("Name", ""),
                "offline": bool(row.get("WorkOffline", False)),
                "status": str(row.get("PrinterStatus", "")),
                "port": row.get("PortName", ""),
            }
            for row in rows
            if row.get("Name")
        ]
    except Exception:
        return []


def diagnose_current_environment() -> dict[str, Any]:
    """Build diagnostics from Print Agent environment without sending a print job."""
    sumatra_path = os.getenv("SUMATRA_PATH", "")
    printer_name = os.getenv("PRINTER_NAME", "")
    return build_print_diagnostics(
        sumatra_path=sumatra_path,
        sumatra_exists=bool(sumatra_path and Path(sumatra_path).exists()),
        printer_name=printer_name,
        printers=collect_windows_printers(),
        queue_count=-1,
        last_error="",
    )


if __name__ == "__main__":
    print(json.dumps(diagnose_current_environment(), ensure_ascii=False, indent=2))
