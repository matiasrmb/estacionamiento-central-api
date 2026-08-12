import unittest
from datetime import datetime
from unittest.mock import patch

from app.api.v1.endpoints import resumen_turno
from app.repositories import operaciones_servicio_repo


class _DbConn:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False


class _ScalarResult:
    def scalar(self):
        return 1500


class _ScalarConnection:
    def __init__(self):
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _ScalarResult()


class ResumenTurnoTests(unittest.TestCase):
    def test_returns_collected_total_and_safe_active_projection(self):
        consultado_a = datetime(2026, 8, 2, 21, 40)
        pendientes = {
            "total_recaudado": 40000,
            "total_banos": 7,
            "total_banos_monto": 2100,
            "total_general": 60100,
            "total_neto": 55600,
        }
        activos = [
            # This active stay already includes its converted wash amount.
            {"monto_acumulado": 6100},
            # Waiting rows are kept for the active count but do not accrue.
            {"monto_acumulado": 0, "en_espera": 1},
        ]

        with patch.object(resumen_turno, "ensure_monthly_payments_schema"), \
             patch.object(resumen_turno, "ensure_noches_schema"), \
             patch.object(resumen_turno, "datetime") as mocked_datetime, \
              patch.object(resumen_turno, "db_conn", return_value=_DbConn()), \
              patch.object(resumen_turno, "build_active_items", return_value=activos) as build_activos, \
              patch.object(resumen_turno, "_build_pending_summary", return_value=pendientes) as build_pendientes, \
              patch.object(resumen_turno, "total_solo_lavados_activos", return_value=1500) as total_lavados:
            mocked_datetime.now.return_value = consultado_a
            result = resumen_turno.obtener_resumen_turno()

        self.assertEqual(result, {
            "consultado_a": "2026-08-02T21:40:00",
            "vehiculos_activos": 2,
            "usos_banos": 7,
            "usos_banos_monto": 2100,
            "total_turno": 60100,
            "total_actual_caja": 60100,
            "estimado_activos": 7600,
            "total_proyectado": 67700,
            "neto_caja": 55600,
        })
        build_activos.assert_called_once()
        self.assertEqual(build_activos.call_args.args[1], consultado_a)
        self.assertEqual(build_activos.call_args.kwargs["as_of"], consultado_a)
        build_pendientes.assert_called_once_with(build_activos.call_args.args[0], as_of=consultado_a)
        total_lavados.assert_called_once_with(build_activos.call_args.args[0], as_of=consultado_a)

    def test_active_wash_projection_excludes_converted_or_unsafe_operations(self):
        consultado_a = datetime(2026, 8, 2, 21, 40)
        conn = _ScalarConnection()

        total = operaciones_servicio_repo.total_solo_lavados_activos(conn, as_of=consultado_a)

        self.assertEqual(total, 1500)
        self.assertIn("estado = 'ACTIVO'", conn.statement)
        self.assertIn("id_ingreso_generado IS NULL", conn.statement)
        self.assertIn("fecha_hora_fin IS NULL", conn.statement)
        self.assertIn("COALESCE(cerrado, FALSE) = FALSE", conn.statement)
        self.assertIn("fecha_hora_inicio <= :as_of", conn.statement)
        self.assertEqual(conn.params, {"as_of": consultado_a})


if __name__ == "__main__":
    unittest.main()
