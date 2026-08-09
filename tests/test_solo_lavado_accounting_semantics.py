import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from app.repositories.cierres_repo import build_cierre_summary_from_rows
from app.repositories.reportes_repo import build_report_totals
from app.services.tarifas import calcular_monto_con_lavados


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
            parking_movements=[{"tipo": "vehiculo", "tarifa_aplicada": 10000}],
            bathroom_uses=[],
            wash_only_operations=[
                {"estado": "CONVERTIDO_ESTADIA", "valor_lavado_snapshot": 9000},
                {"estado": "FINALIZADO_COBRADO", "valor_lavado_snapshot": 8000},
            ],
        )

        self.assertEqual(totals["total_recaudado"], 10000)
        self.assertEqual(totals["total_lavados_solos"], 1)
        self.assertEqual(totals["total_lavados_solos_monto"], 8000)
        self.assertEqual(totals["total_general"], 18000)

    def test_salida_total_includes_converted_solo_lavado_once(self):
        conn = Mock()
        conn.execute.return_value.mappings.return_value.all.return_value = []
        conn.execute.return_value.scalar.side_effect = [0, 9000]

        with patch("app.services.tarifas.calcular_monto_desde_minutos") as calc:
            calc.return_value = (60, 1200, "Base")
            minutos, monto, detalle, monto_estacionamiento, total_lavados = calcular_monto_con_lavados(
                conn,
                42,
                datetime(2026, 7, 1, 10, 0),
                datetime(2026, 7, 1, 11, 0),
            )

        self.assertEqual(minutos, 60)
        self.assertEqual(monto_estacionamiento, 1200)
        self.assertEqual(total_lavados, 9000)
        self.assertEqual(monto, 10200)
        self.assertIn("solo lavado convertido", detalle)


if __name__ == "__main__":
    unittest.main()
