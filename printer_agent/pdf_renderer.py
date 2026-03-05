import os
from datetime import datetime
from typing import Dict, Any

from reportlab.lib.pagesizes import mm
from reportlab.pdfgen import canvas


def _safe_filename(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum() or ch in ("-", "_")).strip() or "ticket"


def render_ticket_pdf(payload: Dict[str, Any], out_dir: str) -> str:
    """
    Renderiza un ticket simple en PDF (58mm aprox) usando ReportLab.

    - No usa imágenes ni logos (MVP).
    - Texto monocromo, estilo ticket.
    - Retorna ruta absoluta del PDF creado.
    """
    os.makedirs(out_dir, exist_ok=True)

    kind = payload.get("kind", "TICKET")
    patente = str(payload.get("patente", "")).upper()
    id_ingreso = payload.get("id_ingreso", "NA")

    # Nombre del archivo
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{_safe_filename(kind)}_{_safe_filename(patente)}_{id_ingreso}_{ts}.pdf"
    path = os.path.abspath(os.path.join(out_dir, fname))

    # Ticket 58mm: ancho 58mm, alto variable (usamos 120mm para MVP)
    width = 58 * mm
    height = 120 * mm

    c = canvas.Canvas(path, pagesize=(width, height))

    y = height - 10 * mm
    line = 5 * mm

    def draw(txt: str, bold: bool = False):
        nonlocal y
        c.setFont("Courier-Bold" if bold else "Courier", 9)
        c.drawString(5 * mm, y, txt[:42])  # corte simple por ancho
        y -= line

    draw("ESTACIONAMIENTO CENTRAL", bold=True)
    draw("------------------------------")
    draw(f"TIPO: {kind}")
    draw(f"PATENTE: {patente}", bold=True)

    if payload.get("hora_ingreso"):
        draw(f"ING: {payload['hora_ingreso']}")
    if payload.get("hora_salida"):
        draw(f"SAL: {payload['hora_salida']}")

    if kind == "TICKET_SALIDA":
        draw("------------------------------")
        draw(f"MIN: {payload.get('minutos_cobrados', '')}")
        draw(f"TOTAL: ${payload.get('monto_final', '')}", bold=True)

        det = payload.get("detalle") or {}
        modo = det.get("modo_tarifa") or det.get("modo") or ""
        if modo:
            draw(f"MODO: {modo}")

    draw("------------------------------")
    usr = payload.get("usuario") or {}
    if usr.get("usuario"):
        draw(f"USR: {usr.get('usuario')} ({usr.get('rol','')})")

    meta = payload.get("meta") or {}
    if meta.get("server_time"):
        draw(f"SRV: {meta['server_time']}")

    draw("")
    draw("Gracias por su preferencia.")

    c.showPage()
    c.save()

    return path