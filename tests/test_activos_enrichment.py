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


class _SnapshotConnection:
    def __init__(self, consultado_a):
        self.consultado_a = consultado_a
        self.calls = []

    def execute(self, statement, params=None):
        query = str(statement)
        self.calls.append((query, params))
        if params != {"as_of": self.consultado_a}:
            raise AssertionError(f"Unexpected snapshot parameters: {params}")
        if "i.fecha_hora_ingreso <= :as_of" not in query:
            raise AssertionError("Snapshot query must exclude future ingresos")
        rows = [{
            "id_ingreso": 1,
            "patente": "PAST01",
            "fecha_hora_ingreso": datetime(2026, 8, 2, 20, 0),
            "en_espera": 0,
            "en_lavado": 0,
            "usuario": "tester",
            # A paid night charge after consultado_a must not suppress this quote.
            "modo_noche": 0,
        }, {
            "id_ingreso": 2,
            "patente": "FUTURE1",
            "fecha_hora_ingreso": datetime(2026, 8, 2, 21, 41),
            "en_espera": 0,
            "en_lavado": 0,
            "usuario": "tester",
            "modo_noche": 0,
        }]
        return _RowsResult([
            row for row in rows
            if row["fecha_hora_ingreso"] <= self.consultado_a
        ])


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

    def test_pending_night_is_not_quoted_as_normal_parking_after_ten(self):
        conn = _Connection([{
            "id_ingreso": 9,
            "patente": "NIGHT01",
            "fecha_hora_ingreso": datetime(2026, 7, 1, 19, 30),
            "en_espera": 0,
            "en_lavado": 0,
            "usuario": "tester",
            "modo_noche": 1,
        }])

        with patch.object(activos, "db_conn", return_value=_DbConn(conn)), \
             patch.object(activos, "calcular_montos_activos_con_lavados", return_value={}) as calcular:
            result = activos.listar_activos()

        item = result["items"][0]
        self.assertEqual(item["monto_acumulado"], 0)
        self.assertEqual(item["minutos_cobrables"], 0)
        calcular.assert_called_once()
        self.assertEqual(calcular.call_args.args[:2], (conn, []))

    def test_snapshot_excludes_future_ingresos_and_night_state(self):
        consultado_a = datetime(2026, 8, 2, 21, 40)
        conn = _SnapshotConnection(consultado_a)

        with patch.object(activos, "calcular_montos_activos_con_lavados", return_value={1: (100, 2500, "detalle", 2500, 0)}) as calcular:
            items = activos.build_active_items(conn, consultado_a, as_of=consultado_a)

        self.assertEqual([(item["id_ingreso"], item["monto_acumulado"]) for item in items], [(1, 2500)])
        query, params = conn.calls[0]
        self.assertIn("i.fecha_hora_ingreso <= :as_of", query)
        self.assertIn("i.fecha_hora_salida > :as_of", query)
        self.assertIn("cn.fecha_hora_pago <= :as_of", query)
        self.assertEqual(params, {"as_of": consultado_a})
        calcular.assert_called_once_with(conn, [{
            "id_ingreso": 1,
            "patente": "PAST01",
            "fecha_hora_ingreso": datetime(2026, 8, 2, 20, 0),
            "en_espera": 0,
            "en_lavado": 0,
            "usuario": "tester",
            "modo_noche": 0,
        }], consultado_a, as_of=consultado_a)


if __name__ == "__main__":
    unittest.main()
