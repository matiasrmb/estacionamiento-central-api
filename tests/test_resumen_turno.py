import unittest
from datetime import datetime
from unittest.mock import patch

from app.api.v1.endpoints import resumen_turno


class _DbConn:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False


class ResumenTurnoTests(unittest.TestCase):
    def test_combines_active_quotes_with_pending_close_totals_at_one_timestamp(self):
        consultado_a = datetime(2026, 8, 2, 21, 40)
        pendientes = {
            "total_recaudado": 40000,
            "total_banos": 7,
            "total_banos_monto": 2100,
            "total_general": 60100,
            "total_neto": 55600,
        }
        activos = [
            {"monto_acumulado": 6100},
            {"monto_acumulado": 0},
        ]

        with patch.object(resumen_turno, "ensure_monthly_payments_schema"), \
             patch.object(resumen_turno, "ensure_noches_schema"), \
             patch.object(resumen_turno, "datetime") as mocked_datetime, \
             patch.object(resumen_turno, "db_conn", return_value=_DbConn()), \
             patch.object(resumen_turno, "build_active_items", return_value=activos) as build_activos, \
             patch.object(resumen_turno, "_build_pending_summary", return_value=pendientes) as build_pendientes:
            mocked_datetime.now.return_value = consultado_a
            result = resumen_turno.obtener_resumen_turno()

        self.assertEqual(result, {
            "consultado_a": "2026-08-02T21:40:00",
            "vehiculos_activos": 2,
            "usos_banos": 7,
            "usos_banos_monto": 2100,
            "total_turno": 48200,
            "total_actual_caja": 60100,
            "neto_caja": 55600,
        })
        build_activos.assert_called_once()
        self.assertEqual(build_activos.call_args.args[1], consultado_a)
        self.assertEqual(build_activos.call_args.kwargs["as_of"], consultado_a)
        build_pendientes.assert_called_once_with(build_activos.call_args.args[0], as_of=consultado_a)


if __name__ == "__main__":
    unittest.main()
