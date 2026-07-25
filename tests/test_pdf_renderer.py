import unittest

from reportlab.pdfbase.pdfmetrics import stringWidth

from printer_agent.pdf_renderer import (
    TICKET_FONT,
    TICKET_FONT_SIZE,
    TICKET_MIN_HEIGHT,
    TICKET_PRINTABLE_WIDTH,
    TICKET_BOTTOM_MARGIN,
    TICKET_LINE_SPACING,
    TICKET_TOP_MARGIN,
    _ticket_lines,
    _ticket_page_height,
    _wrapped_ticket_lines,
    _wrap_ticket_line,
)


class PdfRendererTests(unittest.TestCase):
    def test_salida_renders_modo_subida_y_secciones(self):
        lines = _ticket_lines({
            "kind": "TICKET_SALIDA",
            "patente": "abc123",
            "hora_ingreso": "2026-01-01T10:00:00",
            "hora_salida": "2026-01-01T11:30:00",
            "minutos_cobrados": 60,
            "monto_final": 11500,
            "detalle": {
                "modo_cobro": "personalizado",
                "texto": "Primer tramo",
                "subida_aplicada": True,
                "monto_extra": 500,
                "monto_estacionamiento": 2500,
                "total_lavados": 9000,
                "secciones": {
                    "lavado": {
                        "inicio": "2026-01-01T09:30:00",
                        "fin": "2026-01-01T10:00:00",
                        "duracion_minutos": 30,
                        "monto": 9000,
                    },
                    "estadia": {
                        "inicio": "2026-01-01T10:00:00",
                        "fin": "2026-01-01T11:30:00",
                        "duracion_minutos": 60,
                        "monto": 2500,
                    },
                },
            },
        })

        expected_prefixes = (
            "MODO:",
            "DETALLE:",
            "SUBIDA:",
            "ESTACIONAMIENTO:",
            "LAVADOS:",
            "LAVADO:",
            "ESTADIA:",
            "TOTAL DETALLE:",
        )
        positions = []
        for prefix in expected_prefixes:
            positions.append(next(
                index
                for index, line in enumerate(lines)
                if line.strip().upper().startswith(prefix)
            ))

        self.assertEqual(positions, sorted(positions))

    def test_salida_historica_minima_se_renderiza_sin_campos_nuevos(self):
        lines = _ticket_lines({
            "kind": "TICKET_SALIDA",
            "patente": "abc123",
            "minutos_cobrados": 30,
            "monto_final": 1500,
            "detalle": {"monto_estacionamiento": 1500, "total_lavados": 0},
        })

        self.assertIn("ESTACIONAMIENTO: $1500", lines)
        self.assertIn("TOTAL: $1500", lines)
        self.assertFalse(any(line.startswith("MODO:") for line in lines))

    def test_solo_lavado_renders_receipt_fields_and_fits_58mm(self):
        payload = {
            "kind": "TICKET_SOLO_LAVADO",
            "id_operacion_servicio": 31,
            "patente": "abc123",
            "servicio": "SUV completo",
            "hora_inicio": "2026-07-25T10:00:00",
            "hora_fin": "2026-07-25T10:35:00",
            "minutos": 35,
            "monto_final": 9000,
        }

        lines = _ticket_lines(payload)
        self.assertIn("RECIBO DE SOLO LAVADO", lines)
        self.assertIn("PATENTE: ABC123", lines)
        self.assertIn("INICIO: 25-07-2026 10:00:00", lines)
        self.assertIn("FIN: 25-07-2026 10:35:00", lines)
        self.assertIn("DURACION: 35 min", lines)
        self.assertIn("TOTAL: $9000", lines)

        wrapped_lines = _wrapped_ticket_lines(payload)
        self.assertTrue(all(
            stringWidth(line, "Courier-Bold" if bold else TICKET_FONT, TICKET_FONT_SIZE) <= TICKET_PRINTABLE_WIDTH
            for line, bold in wrapped_lines
        ))
        self.assertGreaterEqual(_ticket_page_height(len(wrapped_lines)), TICKET_MIN_HEIGHT)

    def test_salida_no_muestra_subida_si_no_corresponde(self):
        lines = _ticket_lines({
            "kind": "TICKET_SALIDA",
            "monto_final": 1500,
            "detalle": {"subida_aplicada": False, "monto_extra": 0},
        })

        self.assertFalse(any(line.startswith("SUBIDA:") for line in lines))

    def test_salida_detallada_lines_fit_printable_width(self):
        lines = _ticket_lines({
            "kind": "TICKET_SALIDA",
            "patente": "abc123",
            "hora_ingreso": "2026-01-01T10:00:00",
            "hora_salida": "2026-01-01T11:30:00",
            "minutos_cobrados": 60,
            "monto_final": 11500,
            "detalle": {
                "modo_cobro": "personalizado",
                "texto": "Primer tramo con lavado completo",
                "subida_aplicada": True,
                "monto_extra": 500,
                "monto_estacionamiento": 2500,
                "total_lavados": 9000,
            },
        })

        wrapped_lines = [
            wrapped
            for line in lines
            for wrapped in _wrap_ticket_line(line)
        ]

        self.assertTrue(wrapped_lines)
        self.assertTrue(all(
            stringWidth(line, TICKET_FONT, TICKET_FONT_SIZE) <= TICKET_PRINTABLE_WIDTH
            for line in wrapped_lines
        ))

    def test_long_detail_text_wraps_without_truncation(self):
        detail = "Detalle extraordinariamente largo para comprobar que no se pierda contenido"
        wrapped_lines = _wrap_ticket_line(f"DETALLE: {detail}")

        self.assertGreater(len(wrapped_lines), 1)
        self.assertEqual("".join(wrapped_lines).replace("DETALLE:", "").replace(" ", ""), detail.replace(" ", ""))
        self.assertTrue(all(
            stringWidth(line, TICKET_FONT, TICKET_FONT_SIZE) <= TICKET_PRINTABLE_WIDTH
            for line in wrapped_lines
        ))

    def test_unbroken_token_is_split_to_printable_width(self):
        token = "A" * 100

        wrapped_lines = _wrap_ticket_line(token)

        self.assertGreater(len(wrapped_lines), 1)
        self.assertEqual("".join(wrapped_lines), token)
        self.assertTrue(all(
            stringWidth(line, TICKET_FONT, TICKET_FONT_SIZE) <= TICKET_PRINTABLE_WIDTH
            for line in wrapped_lines
        ))

    def test_wrap_ticket_line_keeps_legacy_width_argument(self):
        token = "A" * 100

        wrapped_lines = _wrap_ticket_line(token, width=32)

        self.assertEqual("".join(wrapped_lines), token)
        self.assertTrue(all(len(line) <= 32 for line in wrapped_lines))

    def test_bold_lines_fit_printable_width_with_bold_metrics(self):
        payload = {
            "kind": "TICKET_SALIDA",
            "patente": "A" * 100,
            "monto_final": "9" * 100,
        }

        bold_lines = [line for line, bold in _wrapped_ticket_lines(payload) if bold]

        self.assertTrue(bold_lines)
        self.assertTrue(all(
            stringWidth(line, "Courier-Bold", TICKET_FONT_SIZE) <= TICKET_PRINTABLE_WIDTH
            for line in bold_lines
        ))

    def test_verbose_salida_page_height_fits_all_wrapped_lines(self):
        payload = {
            "kind": "TICKET_SALIDA",
            "patente": "ABC123",
            "monto_final": 11500,
            "detalle": {
                "texto": "detalle " * 300,
                "secciones": {
                    "lavado": {"duracion_minutos": 30, "monto": 9000},
                    "estadia": {"duracion_minutos": 60, "monto": 2500},
                },
            },
        }

        wrapped_lines = _wrapped_ticket_lines(payload)
        height = _ticket_page_height(len(wrapped_lines))

        self.assertGreater(len(wrapped_lines), 1)
        self.assertGreater(height, TICKET_MIN_HEIGHT)
        self.assertGreaterEqual(
            height,
            TICKET_TOP_MARGIN + (len(wrapped_lines) * TICKET_LINE_SPACING) + TICKET_BOTTOM_MARGIN,
        )


if __name__ == "__main__":
    unittest.main()
