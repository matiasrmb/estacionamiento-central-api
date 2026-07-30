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
    def __init__(self, update_rowcount=1, noches_prepagadas=None, fecha_hora_ingreso=None):
        self.update_rowcount = update_rowcount
        self.noches_prepagadas = noches_prepagadas or []
        self.fecha_hora_ingreso = fecha_hora_ingreso or datetime(2026, 1, 1, 10, 0, 0)
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
                    "fecha_hora_ingreso": self.fecha_hora_ingreso,
                    "fecha_hora_salida": None,
                    "en_lavado": 0,
                    "patente": "ABC123",
                }
            )
        if "FROM cobros_noches" in sql:
            if "SELECT id_cobro_noche, fecha_hora_pago" in sql:
                return MappingResult(None)
            return RowsResult(self.noches_prepagadas)
        if "SUM(valor_lavado_snapshot)" in sql:
            return ScalarResult(0)
        if "SUM(valor_lavado)" in sql:
            return ScalarResult(0)
        if "FROM lavados" in sql:
            return RowsResult([])
        if "UPDATE ingresos" in sql:
            return UpdateResult(self.update_rowcount)
        if "UPDATE cobros_noches" in sql:
            return UpdateResult(1)

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
    def test_preview_separates_prepaid_noches_from_amount_due_now(self):
        conn = FakeConnection(noches_prepagadas=[{
            "monto_snapshot": 5000,
            "hora_inicio_snapshot": "22:00:00",
            "hora_fin_snapshot": "08:00:00",
        }])

        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "calcular_monto_con_lavados", return_value=(60, 1000, "detalle", 1000, 0)):
            result = salidas.preview_salida(salidas.SalidaPreviewIn(id_ingreso=7), _user={"sub": "tester"})

        self.assertEqual(result["monto"], 1000)
        self.assertEqual(result["a_cobrar_ahora"], 1000)
        self.assertEqual(result["total_noches_prepagadas"], 5000)
        self.assertEqual(result["noches_prepagadas"][0]["hora_inicio_snapshot"], "22:00")

    def test_preview_rejects_pending_night_without_calculating_parking(self):
        conn = FakeConnection()
        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "_get_noche_pendiente", return_value={"id_cobro_noche": 9}), \
             patch.object(salidas, "calcular_monto_con_lavados") as calcular:
            with self.assertRaises(HTTPException) as raised:
                salidas.preview_salida(salidas.SalidaPreviewIn(id_ingreso=7), _user={"sub": "tester"})
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "NOCHE_PENDIENTE_DE_REVISION")
        calcular.assert_not_called()

    def test_finalize_pending_night_closes_without_exit_charge_or_ticket(self):
        conn = FakeConnection()
        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "_get_noche_pendiente", return_value={"id_cobro_noche": 9}):
            result = salidas.finalizar_noche(7, user={"sub": "tester"})
        self.assertEqual(result, {"id_ingreso": 7, "estado": "RETIRADO", "monto_adicional": 0})
        self.assertTrue(conn.committed)
        sql = "\n".join(statement for statement, _ in conn.calls)
        self.assertIn("estado_operativo = 'RETIRADO'", sql)
        self.assertIn("tarifa_aplicada = 0", sql)
        self.assertNotIn("TICKET_SALIDA", sql)

    def test_convert_pending_night_anchors_at_the_end_of_the_paid_night(self):
        for pago, resolucion, esperado in (
            (datetime(2026, 7, 30, 9, 30), datetime(2026, 7, 31, 12, 0), datetime(2026, 7, 30, 10, 0)),
            (datetime(2026, 7, 30, 16, 0), datetime(2026, 7, 31, 12, 0), datetime(2026, 7, 31, 10, 0)),
        ):
            with self.subTest(pago=pago):
                conn = FakeConnection()
                with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
                     patch.object(salidas, "_get_noche_pendiente", return_value={
                         "id_cobro_noche": 9, "fecha_hora_pago": pago,
                     }), \
                     patch.object(salidas, "datetime", wraps=datetime) as mocked_datetime:
                    mocked_datetime.now.return_value = resolucion
                    result = salidas.convertir_noche_a_ingreso_normal(7, user={"sub": "tester"})

                self.assertEqual(result["estado"], "CONVERTIDO")
                update_params = next(params for statement, params in conn.calls if "SET fecha_hora_ingreso" in statement)
                self.assertEqual(update_params["inicio_normal"], esperado)

    def test_normal_exit_after_conversion_is_quoted_from_ten(self):
        inicio_normal = datetime(2026, 1, 2, 10, 0, 0)
        conn = FakeConnection(fecha_hora_ingreso=inicio_normal)
        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "calcular_monto_con_lavados", return_value=(60, 1000, "detalle", 1000, 0)) as calcular, \
             patch.object(salidas, "crear_print_job", return_value=True):
            salidas.confirmar_salida(salidas.SalidaConfirmIn(id_ingreso=7), user={"sub": "tester"})

        self.assertEqual(calcular.call_args.args[2], inicio_normal)

    def test_normal_start_is_ten_on_the_paid_night_cycle(self):
        self.assertEqual(
            salidas._inicio_normal_desde_diez(datetime(2026, 1, 2, 10, 0, 0)),
            datetime(2026, 1, 2, 10, 0, 0),
        )

    def test_confirm_update_requires_open_ingreso(self):
        conn = FakeConnection(update_rowcount=1)

        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "calcular_monto_con_lavados", return_value=(60, 1000, "detalle", 1000, 0)), \
             patch.object(salidas, "crear_print_job", return_value=True):
            salidas.confirmar_salida(salidas.SalidaConfirmIn(id_ingreso=7), user={"sub": "tester"})

        update_sql = next(sql for sql, _ in conn.calls if "UPDATE ingresos" in sql)
        self.assertIn("fecha_hora_salida IS NULL", update_sql)

    def test_confirm_raises_conflict_and_skips_print_jobs_when_update_matches_no_rows(self):
        conn = FakeConnection(update_rowcount=0)
        print_calls = []

        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "calcular_monto_con_lavados", return_value=(60, 1000, "detalle", 1000, 0)), \
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
             patch.object(salidas, "calcular_monto_con_lavados", return_value=(60, 1000, "detalle", 1000, 0)), \
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

    def test_confirm_includes_prepaid_noches_without_adding_them_to_exit_charge(self):
        conn = FakeConnection(noches_prepagadas=[{
            "monto_snapshot": 5000,
            "hora_inicio_snapshot": "22:00:00",
            "hora_fin_snapshot": "08:00:00",
        }])
        print_calls = []

        with patch.object(salidas, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(salidas, "calcular_monto_con_lavados", return_value=(60, 1000, "detalle", 1000, 0)), \
             patch.object(salidas, "crear_print_job", side_effect=lambda *args, **kwargs: print_calls.append(kwargs) or True):
            result = salidas.confirmar_salida(salidas.SalidaConfirmIn(id_ingreso=7), user={"sub": "tester"})

        update_params = next(params for sql, params in conn.calls if "UPDATE ingresos" in sql)
        self.assertEqual(update_params["monto"], 1000)
        self.assertEqual(result["a_cobrar_ahora"], 1000)
        self.assertEqual(result["total_noches_prepagadas"], 5000)
        self.assertEqual(print_calls[0]["payload"]["noches_prepagadas"][0]["monto_snapshot"], 5000)


if __name__ == "__main__":
    unittest.main()
