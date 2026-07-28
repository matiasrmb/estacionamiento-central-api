import unittest
from datetime import datetime
from unittest.mock import patch

from app.api.v1.endpoints import activos


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, statement, params=None):
        return _RowsResult(self.rows)


class _DbConn:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class ActivosEnrichmentTests(unittest.TestCase):
    def test_enriches_normal_active_rows_with_shared_exit_quote(self):
        conn = _Connection([{
            "id_ingreso": 7,
            "patente": "ABC123",
            "fecha_hora_ingreso": datetime(2026, 7, 1, 10, 0),
            "en_espera": 0,
            "en_lavado": 0,
            "usuario": "tester",
        }])

        with patch.object(activos, "db_conn", return_value=_DbConn(conn)), \
             patch.object(activos, "calcular_montos_activos_con_lavados", return_value={7: (45, 1800, "detalle", 1800, 0)}) as calcular:
            result = activos.listar_activos()

        item = result["items"][0]
        self.assertEqual(item["monto_acumulado"], 1800)
        self.assertEqual(item["minutos_cobrables"], 45)
        self.assertIsInstance(item["calculado_a"], str)
        self.assertIsNotNone(datetime.fromisoformat(item["calculado_a"]))
        calcular.assert_called_once()

    def test_marks_waiting_rows_as_zero_without_calculating_a_quote(self):
        conn = _Connection([{
            "id_ingreso": 8,
            "patente": "WAIT01",
            "fecha_hora_ingreso": datetime(2026, 7, 1, 10, 0),
            "en_espera": 1,
            "en_lavado": 0,
            "usuario": "tester",
        }])

        with patch.object(activos, "db_conn", return_value=_DbConn(conn)), \
             patch.object(activos, "calcular_montos_activos_con_lavados") as calcular:
            result = activos.listar_activos()

        item = result["items"][0]
        self.assertEqual(item["en_espera"], 1)
        self.assertEqual(item["monto_acumulado"], 0)
        self.assertEqual(item["minutos_cobrables"], 0)
        self.assertIsInstance(item["calculado_a"], str)
        calcular.assert_called_once()
        self.assertEqual(calcular.call_args.args[:2], (conn, []))


if __name__ == "__main__":
    unittest.main()
