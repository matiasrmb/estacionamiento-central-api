import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException

from app.api.v1.endpoints import salidas


class MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class UpdateResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self, update_rowcount=1):
        self.update_rowcount = update_rowcount
        self.calls = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))

        if "FROM ingresos i" in sql:
            return MappingResult(
                {
                    "id_ingreso": 7,
                    "id_vehiculo": 11,
                    "fecha_hora_ingreso": datetime(2026, 1, 1, 10, 0, 0),
                    "fecha_hora_salida": None,
                    "en_lavado": 0,
                    "patente": "ABC123",
                }
            )
        if "SUM(valor_lavado_snapshot)" in sql:
            return ScalarResult(0)
        if "SUM(valor_lavado)" in sql:
            return ScalarResult(0)
        if "FROM lavados" in sql:
            return RowsResult([])
        if "UPDATE ingresos" in sql:
            return UpdateResult(self.update_rowcount)

        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeDbConn:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class SalidasAtomicConfirmTests(unittest.TestCase):
    def test_confirm_update_requires_open_ingreso(self):
        conn = FakeConnection(update_rowcount=1)

        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "calcular_monto_desde_minutos", return_value=(60, 1000, "detalle")), \
             patch.object(salidas, "crear_print_job", return_value=True):
            salidas.confirmar_salida(salidas.SalidaConfirmIn(id_ingreso=7), user={"sub": "tester"})

        update_sql = next(sql for sql, _ in conn.calls if "UPDATE ingresos" in sql)
        self.assertIn("fecha_hora_salida IS NULL", update_sql)

    def test_confirm_raises_conflict_and_skips_print_jobs_when_update_matches_no_rows(self):
        conn = FakeConnection(update_rowcount=0)
        print_calls = []

        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "calcular_monto_desde_minutos", return_value=(60, 1000, "detalle")), \
             patch.object(salidas, "crear_print_job", side_effect=lambda *args, **kwargs: print_calls.append(kwargs)):
            with self.assertRaises(HTTPException) as raised:
                salidas.confirmar_salida(salidas.SalidaConfirmIn(id_ingreso=7), user={"sub": "tester"})

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "INGRESO_YA_SALIO")
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)
        self.assertEqual(print_calls, [])

    def test_confirm_ignores_deprecated_sunmi_flag_and_creates_only_pc_pdf_job(self):
        conn = FakeConnection(update_rowcount=1)
        print_calls = []

        def fake_crear_print_job(*args, **kwargs):
            print_calls.append(kwargs)
            return True

        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "calcular_monto_desde_minutos", return_value=(60, 1000, "detalle")), \
             patch.object(salidas, "crear_print_job", side_effect=fake_crear_print_job):
            result = salidas.confirmar_salida(
                salidas.SalidaConfirmIn(id_ingreso=7, imprimir_sunmi=True),
                user={"sub": "tester"},
            )

        self.assertTrue(conn.committed)
        self.assertFalse(conn.rolled_back)
        self.assertEqual(result["print_jobs_creados"], 1)
        self.assertEqual([call["destino"] for call in print_calls], ["PC_PDF"])
        self.assertNotIn("SUNMI_TEXT", [call["destino"] for call in print_calls])


if __name__ == "__main__":
    unittest.main()
