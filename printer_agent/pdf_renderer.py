import os
from datetime import datetime
from typing import Dict, Any

from reportlab.lib.pagesizes import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


TICKET_WIDTH = 58 * mm
TICKET_MARGIN = 4 * mm
TICKET_FONT = "Courier"
TICKET_FONT_SIZE = 8
TICKET_PRINTABLE_WIDTH = TICKET_WIDTH - (2 * TICKET_MARGIN)
TICKET_TOP_MARGIN = 8 * mm
TICKET_BOTTOM_MARGIN = 8 * mm
TICKET_LINE_SPACING = 4.5 * mm
TICKET_MIN_HEIGHT = 235 * mm


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


def _format_amount(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return str(value or 0)
    return str(int(amount)) if amount.is_integer() else f"{amount:.2f}"


def _format_modo_cobro(value: Any) -> str:
    modo = str(value or "").strip()
    return {
        "minuto": "Por minuto",
        "personalizado": "Tramos",
        "auto": "Automatico",
    }.get(modo.lower(), modo)


def _detail_section_lines(secciones: Any) -> list[str]:
    if not isinstance(secciones, dict):
        return []

    lines: list[str] = []
    total = 0.0
    rendered_sections = 0
    for key, title in (("lavado", "LAVADO"), ("estadia", "ESTADIA")):
        section = secciones.get(key)
        if not isinstance(section, dict):
            continue
        monto = section.get("monto", 0)
        try:
            total += float(monto or 0)
        except (TypeError, ValueError):
            pass
        rendered_sections += 1
        lines.extend([
            f"{title}:",
            f"INICIO: {_format_datetime(section.get('inicio'))}",
            f"FIN: {_format_datetime(section.get('fin'))}",
            f"DURACION: {int(section.get('duracion_minutos') or 0)} min",
            f"MONTO: ${_format_amount(monto)}",
        ])

    if rendered_sections == 2:
        lines.append(f"TOTAL DETALLE: ${_format_amount(total)}")
    return lines


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
        modo_cobro = _format_modo_cobro(det.get("modo_cobro"))
        if modo_cobro:
            lines.append(f"MODO: {modo_cobro}")
        texto_detalle = det.get("texto") or payload.get("detalle_texto") or ""
        if texto_detalle:
            lines.append(f"DETALLE: {texto_detalle}")
        try:
            monto_extra = float(det.get("monto_extra") or 0)
        except (TypeError, ValueError):
            monto_extra = 0
        if det.get("subida_aplicada") or monto_extra > 0:
            lines.append(f"SUBIDA: +${_format_amount(det.get('monto_extra'))}")
        if det.get("monto_estacionamiento") is not None:
            lines.append(f"ESTACIONAMIENTO: ${det.get('monto_estacionamiento')}")
        if det.get("total_lavados"):
            lines.append(f"LAVADOS: ${det.get('total_lavados')}")
        lines.extend(_detail_section_lines(det.get("secciones")))
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


def _wrap_ticket_line(
    text: str,
    width: int | None = None,
    *,
    max_width: float = TICKET_PRINTABLE_WIDTH,
    font_name: str = TICKET_FONT,
    font_size: float = TICKET_FONT_SIZE,
) -> list[str]:
    if text == "":
        return [""]

    if width is not None:
        max_width = stringWidth("M" * width, font_name, font_size)

    if stringWidth(text, font_name, font_size) <= max_width:
        return [text]

    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        for character in word:
            candidate = current + character
            if current and stringWidth(candidate, font_name, font_size) > max_width:
                lines.append(current)
                current = character
            else:
                current = candidate
    if current:
        lines.append(current)
    return lines


def _is_bold_ticket_line(line_text: str) -> bool:
    return line_text.startswith(("TICKET", "PATENTE", "TOTAL"))


def _wrapped_ticket_lines(payload: Dict[str, Any]) -> list[tuple[str, bool]]:
    wrapped_lines: list[tuple[str, bool]] = []
    for line_text in _ticket_lines(payload):
        bold = _is_bold_ticket_line(line_text)
        font_name = "Courier-Bold" if bold else TICKET_FONT
        wrapped_lines.extend(
            (line, bold)
            for line in _wrap_ticket_line(line_text, font_name=font_name)
        )
    return wrapped_lines


def _ticket_page_height(line_count: int) -> float:
    content_height = TICKET_TOP_MARGIN + (line_count * TICKET_LINE_SPACING) + TICKET_BOTTOM_MARGIN
    return max(TICKET_MIN_HEIGHT, content_height)


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

    wrapped_lines = _wrapped_ticket_lines(payload)

    # Ticket 58mm: keep margins on both sides for narrow printer mechanisms.
    width = TICKET_WIDTH
    height = _ticket_page_height(len(wrapped_lines))

    c = canvas.Canvas(path, pagesize=(width, height))

    y = height - TICKET_TOP_MARGIN

    def draw(txt: str, bold: bool = False):
        nonlocal y
        c.setFont("Courier-Bold" if bold else TICKET_FONT, TICKET_FONT_SIZE)
        c.drawString(TICKET_MARGIN, y, txt)
        y -= TICKET_LINE_SPACING

    for line_text, bold in wrapped_lines:
        draw(line_text, bold=bold)

    c.showPage()
    c.save()

    return path
