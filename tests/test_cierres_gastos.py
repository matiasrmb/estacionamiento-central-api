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

        build.assert_called_once_with(conn, lock_expenses=True)
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
