import unittest
from datetime import date, datetime
from unittest.mock import patch

from app.api.v1.endpoints import mensuales
from app.repositories import cierres_repo, mensuales_repo, reportes_repo
from app.repositories.accounting_contracts import build_accounting_summary


class FakeDbConn:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return False


class FakeResult:
    def __init__(self, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.scalar_value


class PaymentConnection:
    def __init__(self, vehicle=None, existing=None):
        self.vehicle = vehicle
        self.existing = existing
        self.executed = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        if "FROM vehiculos" in sql:
            return FakeResult(rows=[self.vehicle] if self.vehicle else [])
        if "FROM pagos_mensuales" in sql:
            return FakeResult(rows=[self.existing] if self.existing else [])
        if "LAST_INSERT_ID" in sql:
            return FakeResult(scalar_value=14)
        return FakeResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class MonthlyPaymentsTests(unittest.TestCase):
    def test_due_date_statuses_and_short_month_due_day(self):
        period = date(2026, 2, 1)
        self.assertEqual(mensuales_repo.effective_due_date(period, 31), date(2026, 2, 28))
        self.assertEqual(mensuales_repo.payment_status(False, period, 31, date(2026, 2, 28)), "pendiente")
        self.assertEqual(mensuales_repo.payment_status(False, period, 31, date(2026, 3, 1)), "vencido")
        self.assertEqual(mensuales_repo.payment_status(True, period, 1, date(2026, 2, 1)), "pagado")

    def test_list_includes_current_period_payment_state(self):
        class ListConnection:
            def execute(self, _statement, params=None):
                self.params = params
                return FakeResult(rows=[{
                    "id_vehiculo": 8,
                    "patente": "AAA111",
                    "tarifa_mensual": 25000,
                    "dia_vencimiento": 31,
                    "id_pago_mensual": 4,
                    "fecha_pago": datetime(2026, 2, 15, 10, 0),
                    "monto_snapshot": 24000,
                }])

        conn = ListConnection()
        with patch.object(mensuales_repo, "db_conn", return_value=FakeDbConn(conn)):
            items = mensuales_repo.list_mensuales(date(2026, 2, 20))

        self.assertEqual(conn.params["periodo"], date(2026, 2, 1))
        self.assertEqual(items[0]["estado_pago"], "pagado")
        self.assertTrue(items[0]["pagado_periodo_actual"])
        self.assertEqual(items[0]["periodo_actual"], "2026-02-01")

    def test_register_payment_snapshots_server_values(self):
        conn = PaymentConnection(vehicle={"tarifa_mensual": 25000, "dia_vencimiento": 15})
        now = datetime(2026, 7, 8, 9, 30)
        with patch.object(mensuales_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = mensuales_repo.register_monthly_payment(8, "admin", "efectivo", "Julio", now)

        insert = next(entry for entry in conn.executed if "INSERT INTO pagos_mensuales" in entry[0])
        self.assertEqual(insert[1]["periodo"], date(2026, 7, 1))
        self.assertEqual(insert[1]["monto_snapshot"], 25000)
        self.assertEqual(insert[1]["dia_vencimiento_snapshot"], 15)
        self.assertEqual(insert[1]["fecha_pago"], now)
        self.assertEqual(insert[1]["usuario"], "admin")
        self.assertEqual(result["id_pago_mensual"], 14)
        self.assertTrue(conn.committed)

    def test_register_payment_rejects_duplicate_inactive_and_nonpositive_fee(self):
        cases = [
            (PaymentConnection(vehicle={"tarifa_mensual": 25000, "dia_vencimiento": 1}, existing={"id_pago_mensual": 2}), ValueError, "MONTHLY_PAYMENT_ALREADY_EXISTS"),
            (PaymentConnection(vehicle=None), LookupError, "MENSUAL_NOT_FOUND"),
            (PaymentConnection(vehicle={"tarifa_mensual": 0, "dia_vencimiento": 1}), ValueError, "INVALID_MONTHLY_FEE"),
        ]
        for conn, error_type, code in cases:
            with self.subTest(code=code), patch.object(mensuales_repo, "db_conn", return_value=FakeDbConn(conn)):
                with self.assertRaisesRegex(error_type, code):
                    mensuales_repo.register_monthly_payment(8, "admin", now=datetime(2026, 7, 8, 9, 30))
            self.assertTrue(conn.rolled_back)

    def test_payment_endpoint_maps_duplicate_to_conflict(self):
        payload = mensuales.PagoMensualIn()
        with patch.object(mensuales, "register_monthly_payment", side_effect=ValueError("MONTHLY_PAYMENT_ALREADY_EXISTS")):
            with self.assertRaises(Exception) as raised:
                mensuales.registrar_pago_mensual(8, payload, user={"sub": "admin"})
        self.assertEqual(raised.exception.status_code, 409)

    def test_payment_only_and_mixed_close_include_monthly_revenue(self):
        payment = {"id_pago_mensual": 6, "fecha_pago": datetime(2026, 7, 1, 9, 0), "monto_snapshot": 25000}
        summary = cierres_repo.build_cierre_summary_from_rows([], [], [], datetime(2026, 7, 1, 10, 0), monthly_payments=[payment])
        self.assertTrue(summary["hay_pendiente"])
        self.assertEqual(summary["total_mensualidades"], 1)
        self.assertEqual(summary["total_general"], 25000)
        self.assertEqual(summary["ids_pagos_mensuales"], [6])

        mixed = build_accounting_summary(
            [{"tarifa_aplicada": 1200}], [], [], [{"monto": 200}], [{"monto_snapshot": 25000}]
        )
        self.assertEqual(mixed["total_general"], 26200)
        self.assertEqual(mixed["total_neto"], 26000)

    def test_link_monthly_payments_updates_only_selected_unclosed_rows(self):
        conn = PaymentConnection()
        cierres_repo._link_monthly_payments_to_cierre(conn, [6, 9], 31)
        sql, params = conn.executed[0]
        self.assertIn("id_cierre IS NULL", sql)
        self.assertIn("id_pago_mensual IN (:payment_id_0, :payment_id_1)", sql)
        self.assertEqual(params, {"id_cierre": 31, "payment_id_0": 6, "payment_id_1": 9})

    def test_plate_filtered_report_includes_monthly_payment_and_totals(self):
        class ReportConnection:
            def __init__(self):
                self.executed = []

            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append((sql, params))
                if "FROM ingresos" in sql:
                    return FakeResult(rows=[{
                        "patente": "AAA111",
                        "fecha_hora_ingreso": datetime(2026, 7, 1, 9, 0),
                        "fecha_hora_salida": datetime(2026, 7, 1, 10, 0),
                        "minutos": 60,
                        "tarifa_aplicada": 1200,
                    }])
                if "FROM pagos_mensuales" in sql:
                    return FakeResult(rows=[{
                        "patente": "AAA111",
                        "fecha_pago": datetime(2026, 7, 1, 11, 0),
                        "monto_snapshot": 25000,
                        "usuario": "admin",
                        "metodo_pago": "efectivo",
                        "observacion": None,
                        "periodo": date(2026, 7, 1),
                    }])
                return FakeResult()

        conn = ReportConnection()
        with patch.object(reportes_repo, "db_conn", return_value=FakeDbConn(conn)):
            report = reportes_repo.obtener_reporte(date(2026, 7, 1), date(2026, 7, 1), "aaa111")

        monthly_query, monthly_params = next(entry for entry in conn.executed if "FROM pagos_mensuales" in entry[0])
        self.assertIn("v.patente = :patente", monthly_query)
        self.assertEqual(monthly_params["patente"], "AAA111")
        self.assertEqual([item["tipo"] for item in report["items"]], ["vehiculo", "pago_mensual"])
        self.assertEqual(report["total_mensualidades"], 1)
        self.assertEqual(report["total_mensualidades_monto"], 25000)
        self.assertEqual(report["total_general"], 26200)
        self.assertEqual(report["total_movimientos"], 2)


if __name__ == "__main__":
    unittest.main()
