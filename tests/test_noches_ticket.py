from datetime import datetime
import unittest

from app.services.tickets_service import build_ticket_ingreso_payload
from printer_agent.pdf_renderer import _ticket_lines


class NochesTicketTests(unittest.TestCase):
    def test_ingreso_ticket_includes_prepaid_noches_detail(self):
        payload = build_ticket_ingreso_payload(
            id_ingreso=10,
            patente="ABC123",
            hora_ingreso_iso=datetime(2026, 7, 30, 22, 0).isoformat(),
            usuario_claims={"sub": "operador"},
            server_time_iso=datetime(2026, 7, 30, 22, 0).isoformat(),
            cobro_noche={
                "monto_snapshot": 5000,
                "hora_inicio_snapshot": "22:00",
                "hora_fin_snapshot": "08:00",
            },
        )

        self.assertEqual(payload["noches"]["monto_snapshot"], 5000)
        lines = _ticket_lines(payload)
        self.assertIn("NOCHES PREPAGADAS: $5000", lines)
        self.assertIn("REFERENCIA: 22:00 A 08:00", lines)
