import unittest
from datetime import datetime

from app.repositories.cierres_repo import build_cierre_summary_from_rows
from app.repositories.reportes_repo import build_report_totals


class SoloLavadoAccountingSemanticsTests(unittest.TestCase):
    def test_pending_cierre_includes_charge_now_solo_lavado_in_total_general(self):
        summary = build_cierre_summary_from_rows(
            parking_movements=[
                {
                    "id_ingreso": 1,
                    "fecha_hora_ingreso": datetime(2026, 7, 1, 9, 0),
                    "fecha_hora_salida": datetime(2026, 7, 1, 10, 0),
                    "tarifa_aplicada": 1200,
                }
            ],
            bathroom_uses=[{"monto": 300}],
            wash_only_operations=[{"estado": "FINALIZADO_COBRADO", "valor_lavado_snapshot": 9000}],
            fecha_cierre=datetime(2026, 7, 1, 12, 0),
        )

        self.assertEqual(summary["total_recaudado"], 1200)
        self.assertEqual(summary["total_lavados_solos"], 1)
        self.assertEqual(summary["total_lavados_solos_monto"], 9000)
        self.assertEqual(summary["total_general"], 10500)

    def test_report_totals_exclude_converted_solo_lavado_until_parking_exit(self):
        totals = build_report_totals(
            items=[{"tipo": "vehiculo", "tarifa_aplicada": 10000}],
            wash_only_operations=[
                {"estado": "CONVERTIDO_ESTADIA", "valor_lavado_snapshot": 9000},
                {"estado": "FINALIZADO_COBRADO", "valor_lavado_snapshot": 8000},
            ],
        )

        self.assertEqual(totals["total_recaudado"], 10000)
        self.assertEqual(totals["total_lavados_solos"], 1)
        self.assertEqual(totals["total_lavados_solos_monto"], 8000)
        self.assertEqual(totals["total_general"], 18000)


if __name__ == "__main__":
    unittest.main()
