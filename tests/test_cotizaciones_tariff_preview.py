import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app.services import tarifas_service


class CotizacionesTariffPreviewTests(unittest.TestCase):
    def test_preview_cycles_custom_tariff_for_multi_hour_quote(self):
        ingreso = datetime(2026, 1, 1, 13, 0, 0)
        salida = ingreso + timedelta(minutes=360)

        with patch.object(tarifas_service, "db_conn") as db_conn_mock:
            conn = db_conn_mock.return_value.__enter__.return_value
            conn.execute.return_value.fetchall.side_effect = [
                [("modo_cobro", "personalizado"), ("tarifa_minima", "300")],
                [(0, 60, 1300)],
            ]
            conn.execute.return_value.fetchone.return_value = None

            preview = tarifas_service.calcular_monto_preview(ingreso, salida)

        self.assertEqual(preview["minutos_cobrados"], 360)
        self.assertEqual(preview["monto"], 7800)


if __name__ == "__main__":
    unittest.main()
