import os
import time
import subprocess
from pathlib import Path


class AmbiguousPrintDispatchError(RuntimeError):
    """The print command was started, so physical output cannot be ruled out."""


class PrintDispatchStartError(RuntimeError):
    """Sumatra could not be started, so the job can be retried automatically."""


def _ps(cmd: str, timeout: int = 15) -> tuple[int, str, str]:
    """
    Ejecuta PowerShell y retorna (rc, stdout, stderr).
    """
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def _printer_preflight(printer_name: str) -> None:
    """
    Verifica que la impresora exista y no esté en modo offline.
    Si falla, levantamos excepción para que el job NO se marque IMPRESO.
    """
    rc, out, err = _ps(
        f"$p=Get-Printer -Name '{printer_name}' -ErrorAction SilentlyContinue;"
        f"if($null -eq $p){{'__NOT_FOUND__'}} else {{"
        f"'NAME=' + $p.Name; 'OFFLINE=' + $p.WorkOffline; 'STATUS=' + $p.PrinterStatus; 'PORT=' + $p.PortName"
        f"}}"
    )
    text_out = (out or "").strip()
    if "__NOT_FOUND__" in text_out:
        raise RuntimeError(f"Printer not found: '{printer_name}'")
    # Si está offline, falla (muchas veces tras reinicio queda offline aunque imprimas “manual” desde otra app por spooler timing)
    if "OFFLINE=True" in text_out:
        raise RuntimeError(f"Printer '{printer_name}' is offline. Details: {text_out}")


def _queue_count(printer_name: str) -> int:
    """
    Cuenta trabajos en cola. Si no se puede consultar, retorna -1.
    """
    rc, out, err = _ps(
        f"(Get-PrintJob -PrinterName '{printer_name}' -ErrorAction SilentlyContinue | Measure-Object).Count"
    )
    s = (out or "").strip()
    try:
        return int(s)
    except Exception:
        return -1


def print_pdf_with_sumatra(*, sumatra_path: str, pdf_path: str, printer_name: str, timeout_seconds: int = 20) -> None:
    """
    Impresión silenciosa y estable con SumatraPDF.
    Comando:
      SumatraPDF.exe -print-to "<printer>" -silent "<pdf>"
    """
    exe = Path(sumatra_path)
    if not exe.exists():
        raise PrintDispatchStartError(f"SumatraPDF not found: {sumatra_path}")

    pdf = Path(pdf_path)
    if not pdf.exists():
        raise PrintDispatchStartError(f"PDF not found: {pdf_path}")

    cmd = [
        str(exe),
        "-print-to", printer_name,
        "-silent",
        str(pdf),
    ]

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
    except (FileNotFoundError, OSError) as exc:
        raise PrintDispatchStartError(f"Could not start Sumatra: {exc}") from exc
    except Exception as exc:
        raise AmbiguousPrintDispatchError(f"Sumatra dispatch did not complete: {exc}") from exc

    if p.returncode != 0:
        raise AmbiguousPrintDispatchError(
            f"Sumatra print failed rc={p.returncode} stderr={p.stderr.strip()} stdout={p.stdout.strip()}"
        )

    # Pequeña pausa para evitar ráfagas en térmicas
    time.sleep(0.5)
