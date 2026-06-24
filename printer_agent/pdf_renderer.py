import os
from datetime import datetime
from typing import Dict, Any

from reportlab.lib.pagesizes import mm
from reportlab.pdfgen import canvas


def _safe_filename(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum() or ch in ("-", "_")).strip() or "ticket"


def _format_datetime(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    normalized = text.replace("T", " ").split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.strftime("%d-%m-%Y %H:%M:%S")
        except ValueError:
            pass
    return normalized


def _ticket_lines(payload: Dict[str, Any]) -> list[str]:
    kind = payload.get("kind", "TICKET")
    patente = str(payload.get("patente", "")).upper()
    hora_ingreso = _format_datetime(payload.get("hora_ingreso") or payload.get("fecha_hora_ingreso"))
    hora_salida = _format_datetime(payload.get("hora_salida") or payload.get("fecha_hora_salida"))
    top_margin = ["------------------------", "------------------------"]
    bottom_margin = ["------------------------", "------------------------", "------------------------"]

    lines = [
        *top_margin,
        "ESTACIONAMIENTO CENTRAL",
        "------------------------",
        "TICKET DE INGRESO" if kind == "TICKET_INGRESO" else "TICKET DE SALIDA",
        f"PATENTE: {patente}",
    ]

    if hora_ingreso:
        lines.append(f"INGRESO: {hora_ingreso}")

    if kind == "TICKET_SALIDA":
        if hora_salida:
            lines.append(f"SALIDA: {hora_salida}")
        lines.extend([
            f"TIEMPO: {payload.get('minutos_cobrados', payload.get('minutos', ''))} min",
            "------------------------",
        ])

        det = payload.get("detalle") or {}
        texto_detalle = det.get("texto") or payload.get("detalle_texto") or ""
        if texto_detalle:
            lines.append(f"DETALLE: {texto_detalle}")
        if det.get("monto_estacionamiento") is not None:
            lines.append(f"ESTACIONAMIENTO: ${det.get('monto_estacionamiento')}")
        if det.get("total_lavados"):
            lines.append(f"LAVADOS: ${det.get('total_lavados')}")
        lines.extend([
            "------------------------",
            f"TOTAL: ${payload.get('monto_final', payload.get('monto', ''))}",
        ])

    lines.extend([
        "------------------------",
        "Gracias por su visita.",
        *bottom_margin,
    ])
    return lines


def _wrap_ticket_line(text: str, width: int = 32) -> list[str]:
    if text == "":
        return [""]

    if len(text) <= width:
        return [text]

    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:width]
    if current:
        lines.append(current)
    return lines


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

    # Ticket 58mm: ancho 58mm, con margen extra para facilitar el corte.
    width = 58 * mm
    height = 235 * mm

    c = canvas.Canvas(path, pagesize=(width, height))

    y = height - 8 * mm
    line = 6.5 * mm

    def draw(txt: str, bold: bool = False):
        nonlocal y
        c.setFont("Courier-Bold" if bold else "Courier", 12)
        c.drawString(4 * mm, y, txt[:29])  # corte simple por ancho
        y -= line

    for line_text in _ticket_lines(payload):
        bold = line_text.startswith("TICKET") or line_text.startswith("PATENTE") or line_text.startswith("TOTAL")
        for wrapped in _wrap_ticket_line(line_text):
            draw(wrapped, bold=bold)

    c.showPage()
    c.save()

    return path
