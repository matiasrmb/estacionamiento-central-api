import unittest
from datetime import datetime
from unittest.mock import patch

from app.repositories import cierres_repo


class FakeDbConn:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return False


class FakeResult:
    def __init__(self, scalar_value=None, rows=None):
        self.scalar_value = scalar_value
        self.rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar(self):
        return self.scalar_value


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        if "GET_LOCK" in sql:
            return FakeResult(scalar_value=1)
        if "LAST_INSERT_ID" in sql:
            return FakeResult(scalar_value=31)
        return FakeResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class CierresGastosTests(unittest.TestCase):
    def test_mixed_close_keeps_gross_revenue_and_subtracts_expenses_from_net(self):
        summary = cierres_repo.build_cierre_summary_from_rows(
            parking_movements=[{
                "id_ingreso": 1,
                "fecha_hora_ingreso": datetime(2026, 7, 1, 9, 0),
                "tarifa_aplicada": 1200,
            }],
            bathroom_uses=[{"fecha_hora": datetime(2026, 7, 1, 9, 30), "monto": 300}],
            wash_only_operations=[{
                "id_operacion_servicio": 2,
                "fecha_hora_fin": datetime(2026, 7, 1, 10, 0),
                "estado": "FINALIZADO_COBRADO",
                "valor_lavado_snapshot": 9000,
            }],
            expenses=[{"id_gasto": 5, "fecha_hora": datetime(2026, 7, 1, 8, 0), "monto": 700}],
            fecha_cierre=datetime(2026, 7, 1, 12, 0),
        )

        self.assertEqual(summary["total_general"], 10500)
        self.assertEqual(summary["total_gastos"], 700)
        self.assertEqual(summary["total_neto"], 9800)
        self.assertEqual(summary["fecha_inicio"], datetime(2026, 7, 1, 8, 0))

    def test_pending_summary_locks_and_selects_unlinked_bathrooms_by_id(self):
        class PendingConnection:
            def __init__(self):
                self.executed = []
                self.results = [
                    FakeResult(rows=[]),
                    FakeResult(rows=[]),
                    FakeResult(rows=[]),
                    FakeResult(rows=[{"id_uso_bano": 9, "fecha_hora": datetime(2026, 7, 1, 9, 0), "monto": 300}]),
                    FakeResult(rows=[]),
                    FakeResult(rows=[]),
                ]

            def execute(self, statement, params=None):
                self.executed.append((str(statement), params))
                return self.results.pop(0)

        conn = PendingConnection()
        summary = cierres_repo._build_pending_summary(conn, lock_expenses=True)

        ingresos_query = conn.executed[0][0]
        self.assertIn("FROM ingresos", ingresos_query)
        self.assertIn("FOR UPDATE", ingresos_query)
        wash_only_query = conn.executed[1][0]
        self.assertIn("FROM operaciones_servicio", wash_only_query)
        self.assertIn("FOR UPDATE", wash_only_query)
        expense_query = conn.executed[2][0]
        self.assertIn("WHERE id_cierre IS NULL", expense_query)
        self.assertIn("FOR UPDATE", expense_query)
        bathroom_query = conn.executed[3][0]
        self.assertIn("SELECT id AS id_uso_bano", bathroom_query)
        self.assertIn("ORDER BY fecha_hora ASC, id ASC", bathroom_query)
        self.assertIn("WHERE id_cierre IS NULL", bathroom_query)
        self.assertIn("FOR UPDATE", bathroom_query)
        self.assertNotIn("MAX(fecha_cierre)", bathroom_query)
        monthly_payments_query = conn.executed[4][0]
        self.assertIn("FROM pagos_mensuales", monthly_payments_query)
        self.assertIn("WHERE id_cierre IS NULL", monthly_payments_query)
        self.assertIn("FOR UPDATE", monthly_payments_query)
        night_charges_query = conn.executed[5][0]
        self.assertIn("FROM cobros_noches", night_charges_query)
        self.assertIn("fecha_hora_pago", night_charges_query)
        self.assertIn("id_cierre IS NULL", night_charges_query)
        self.assertIn("FOR UPDATE", night_charges_query)
        self.assertTrue(summary["hay_pendiente"])
        self.assertEqual(summary["total_banos_monto"], 300)
        self.assertEqual(summary["fecha_inicio"], datetime(2026, 7, 1, 9, 0))
        self.assertEqual(summary["ids_banos"], [9])

    def test_pending_summary_as_of_excludes_operations_after_the_snapshot(self):
        as_of = datetime(2026, 7, 1, 10, 0)
        before = datetime(2026, 7, 1, 9, 0)
        after = datetime(2026, 7, 1, 11, 0)

        class SnapshotConnection:
            def execute(self, statement, params=None):
                sql = str(statement)
                if "FROM ingresos" in sql:
                    rows, field = [
                        {"id_ingreso": 1, "fecha_hora_ingreso": before, "fecha_hora_salida": before, "tarifa_aplicada": 1000},
                        {"id_ingreso": 2, "fecha_hora_ingreso": after, "fecha_hora_salida": after, "tarifa_aplicada": 2000},
                    ], "fecha_hora_salida"
                elif "FROM operaciones_servicio" in sql:
                    rows, field = [
                        {"id_operacion_servicio": 3, "fecha_hora_fin": before, "estado": "FINALIZADO_COBRADO", "valor_lavado_snapshot": 3000},
                        {"id_operacion_servicio": 4, "fecha_hora_fin": after, "estado": "FINALIZADO_COBRADO", "valor_lavado_snapshot": 4000},
                    ], "fecha_hora_fin"
                elif "FROM gastos_operacion" in sql:
                    rows, field = [
                        {"id_gasto": 5, "fecha_hora": before, "monto": 500},
                        {"id_gasto": 6, "fecha_hora": after, "monto": 600},
                    ], "fecha_hora"
                elif "FROM usos_bano" in sql:
                    rows, field = [
                        {"id_uso_bano": 7, "fecha_hora": before, "monto": 200},
                        {"id_uso_bano": 8, "fecha_hora": after, "monto": 300},
                    ], "fecha_hora"
                elif "FROM pagos_mensuales" in sql:
                    rows, field = [
                        {"id_pago_mensual": 9, "fecha_pago": before, "monto_snapshot": 5000},
                        {"id_pago_mensual": 10, "fecha_pago": after, "monto_snapshot": 6000},
                    ], "fecha_pago"
                else:
                    rows, field = [], "fecha_hora_pago"

                if ":as_of" in sql:
                    rows = [row for row in rows if row[field] <= params["as_of"]]
                return FakeResult(rows=rows)

        summary = cierres_repo._build_pending_summary(SnapshotConnection(), as_of=as_of)

        self.assertEqual(summary["ids_ingresos"], [1])
        self.assertEqual(summary["ids_operaciones_servicio"], [3])
        self.assertEqual(summary["ids_gastos"], [5])
        self.assertEqual(summary["ids_banos"], [7])
        self.assertEqual(summary["ids_pagos_mensuales"], [9])
        self.assertEqual(summary["total_general"], 9200)
        self.assertEqual(summary["total_gastos"], 500)

    def test_expense_only_close_is_valid_and_links_only_selected_expenses(self):
        conn = FakeConnection()
        summary = {
            "hay_pendiente": True,
            "fecha_inicio": datetime(2026, 7, 1, 9, 0),
            "fecha_cierre": datetime(2026, 7, 1, 10, 0),
            "total_recaudado": 0,
            "total_ingresos": 0,
            "total_salidas": 0,
            "total_banos": 0,
            "total_banos_monto": 0,
            "total_lavados_solos": 0,
            "total_lavados_solos_monto": 0,
            "total_general": 0,
            "total_gastos": 700,
            "total_neto": -700,
            "ids_ingresos": [],
            "ids_operaciones_servicio": [],
            "ids_banos": [3, 4],
            "ids_gastos": [5, 8],
        }
        with patch.object(cierres_repo, "ensure_monthly_payments_schema"), \
             patch.object(cierres_repo, "ensure_noches_schema"), \
             patch.object(cierres_repo, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(cierres_repo, "_build_pending_summary", return_value=summary) as build:
            result = cierres_repo.realizar_cierre("admin")

        build.assert_called_once()
        self.assertEqual(build.call_args.args, (conn,))
        self.assertEqual(
            build.call_args.kwargs,
            {
                "lock_expenses": True,
                "fecha_cierre": build.call_args.kwargs["as_of"],
                "as_of": build.call_args.kwargs["as_of"],
            },
        )
        self.assertEqual(result["total_general"], 0)
        self.assertEqual(result["total_neto"], -700)
        expenses_update = next((entry for entry in conn.executed if "UPDATE gastos_operacion" in entry[0]), None)
        self.assertIsNotNone(expenses_update)
        self.assertIn("id_gasto IN (:expense_id_0, :expense_id_1)", expenses_update[0])
        self.assertEqual(expenses_update[1], {"id_cierre": 31, "expense_id_0": 5, "expense_id_1": 8})
        bathrooms_update = next((entry for entry in conn.executed if "UPDATE usos_bano" in entry[0]), None)
        self.assertIsNotNone(bathrooms_update)
        self.assertIn("id IN (:bathroom_use_id_0, :bathroom_use_id_1)", bathrooms_update[0])
        self.assertEqual(
            bathrooms_update[1],
            {"id_cierre": 31, "bathroom_use_id_0": 3, "bathroom_use_id_1": 4},
        )
        self.assertTrue(conn.committed)

    def test_close_marks_only_the_selected_ingresos_and_wash_operations(self):
        conn = FakeConnection()
        summary = {
            "hay_pendiente": True,
            "fecha_inicio": datetime(2026, 7, 1, 9, 0),
            "fecha_cierre": datetime(2026, 7, 1, 10, 0),
            "total_recaudado": 1000,
            "total_ingresos": 1,
            "total_salidas": 1,
            "total_banos": 0,
            "total_banos_monto": 0,
            "total_lavados_solos": 1,
            "total_lavados_solos_monto": 9000,
            "total_mensualidades": 0,
            "total_mensualidades_monto": 0,
            "total_noches": 0,
            "total_noches_monto": 0,
            "total_general": 10000,
            "total_gastos": 0,
            "total_neto": 10000,
            "ids_ingresos": [7],
            "ids_operaciones_servicio": [11],
            "ids_banos": [],
            "ids_gastos": [],
            "ids_pagos_mensuales": [],
            "ids_cobros_noches": [],
        }
        with patch.object(cierres_repo, "ensure_monthly_payments_schema"), \
             patch.object(cierres_repo, "ensure_noches_schema"), \
             patch.object(cierres_repo, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(cierres_repo, "_build_pending_summary", return_value=summary):
            cierres_repo.realizar_cierre("operador")

        ingresos_update = next(entry for entry in conn.executed if "UPDATE ingresos" in entry[0])
        self.assertIn("id_ingreso IN (:ingreso_id_0)", ingresos_update[0])
        self.assertNotIn("fecha_hora_salida <=", ingresos_update[0])
        self.assertEqual(ingresos_update[1], {"ingreso_id_0": 7})
        wash_update = next(entry for entry in conn.executed if "UPDATE operaciones_servicio" in entry[0])
        self.assertIn("id_operacion_servicio IN (:operation_id_0)", wash_update[0])
        self.assertNotIn("fecha_hora_fin <=", wash_update[0])
        self.assertEqual(wash_update[1], {"operation_id_0": 11})

    def test_close_fails_fast_when_the_database_lock_is_unavailable(self):
        conn = FakeConnection()

        def unavailable_lock(statement, params=None):
            conn.executed.append((str(statement), params))
            if "GET_LOCK" in str(statement):
                return FakeResult(scalar_value=0)
            return FakeResult()

        conn.execute = unavailable_lock
        with patch.object(cierres_repo, "ensure_monthly_payments_schema"), \
             patch.object(cierres_repo, "ensure_noches_schema"), \
             patch.object(cierres_repo, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(cierres_repo, "_build_pending_summary") as build:
            with self.assertRaises(cierres_repo.DailyCloseInProgressError):
                cierres_repo.realizar_cierre("operador")

        build.assert_not_called()
        self.assertTrue(conn.rolled_back)
        self.assertFalse(any("RELEASE_LOCK" in sql for sql, _ in conn.executed))

    def test_no_pending_close_does_not_link_expenses(self):
        conn = FakeConnection()
        with patch.object(cierres_repo, "ensure_monthly_payments_schema"), \
             patch.object(cierres_repo, "ensure_noches_schema"), \
             patch.object(cierres_repo, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(cierres_repo, "_build_pending_summary", return_value={"hay_pendiente": False}):
            with self.assertRaises(LookupError):
                cierres_repo.realizar_cierre("admin")

        self.assertFalse(any("UPDATE gastos_operacion" in sql for sql, _ in conn.executed))
        self.assertTrue(conn.rolled_back)

    def test_prepaid_nights_use_payment_time_and_are_linked_once(self):
        summary = cierres_repo.build_cierre_summary_from_rows(
            parking_movements=[],
            bathroom_uses=[],
            wash_only_operations=[],
            fecha_cierre=datetime(2026, 7, 2, 1, 0),
            night_charges=[{
                "id_cobro_noche": 14,
                "fecha_hora_pago": datetime(2026, 7, 1, 22, 0),
                "monto_snapshot": 5000,
            }],
        )

        self.assertEqual(summary["fecha_inicio"], datetime(2026, 7, 1, 22, 0))
        self.assertEqual(summary["total_noches_monto"], 5000)
        self.assertEqual(summary["total_general"], 5000)
        self.assertEqual(summary["ids_cobros_noches"], [14])

        conn = FakeConnection()
        cierres_repo._link_night_charges_to_cierre(conn, [14], 31)
        update = next(entry for entry in conn.executed if "UPDATE cobros_noches" in entry[0])
        self.assertIn("id_cierre IS NULL", update[0])
        self.assertIn("estado = 'PAGADO'", update[0])
        self.assertEqual(update[1], {"id_cierre": 31, "night_charge_id_0": 14})


if __name__ == "__main__":
    unittest.main()
