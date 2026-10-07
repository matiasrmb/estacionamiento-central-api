from datetime import datetime
from contextlib import nullcontext
import unittest
from unittest.mock import MagicMock, patch

from app.repositories.reporting_read_models import (
    build_audit_inventory,
    build_closed_report,
)


class ReportingClosedReportsTests(unittest.TestCase):
    def test_closed_report_preserves_closure_reference_and_operation_drill_down(self):
        report = build_closed_report(
            closure={
                "id": 44,
                "period_start": datetime(2026, 9, 28, 9, 30),
                "closed_at": datetime(2026, 9, 29, 2, 0),
                "operational_income_total": 1000,
                "operational_expense_total": 100,
                "mensualidad_sales_total": 250,
            },
            vehicle_movements=[
                {"id": 1, "occurred_at": datetime(2026, 9, 28, 10, 0), "amount": 400, "plate": "ABC123"},
                {"id": 2, "occurred_at": datetime(2026, 9, 28, 11, 0), "amount": 600, "plate": "XYZ987"},
            ],
            expenses=[{"id": 8, "occurred_at": datetime(2026, 9, 28, 12, 0), "amount": 100}],
        )

        self.assertEqual(report["closure_reference"]["id"], 44)
        self.assertEqual(report["closure_reference"]["metrics"]["operational_income_total"], 1000)
        self.assertEqual(report["operation_totals"]["operational_net_total"], 900)
        self.assertEqual(report["closure_reference"]["metrics"]["operational_net_total"], 1150)
        self.assertEqual(report["capacity"]["source_state"], "unavailable")
        self.assertEqual(report["historical_completeness"]["status"], "partial")
        self.assertIn("historical-capacity-limited", report["historical_completeness"]["unavailable_inputs"])
        self.assertEqual(report["operation_drill_down"][0]["canonical_category"], "vehicle_movement")
        self.assertEqual(report["discrepancy"]["status"], "delta")

    def test_closed_report_shows_delta_discrepancy_without_rewriting_closure(self):
        report = build_closed_report(
            closure={
                "id": 45,
                "period_start": datetime(2026, 9, 28, 9, 30),
                "closed_at": datetime(2026, 9, 29, 2, 0),
                "operational_income_total": 1000,
                "operational_expense_total": 0,
                "mensualidad_sales_total": 0,
            },
            vehicle_movements=[{"id": 3, "occurred_at": datetime(2026, 9, 28, 10, 0), "amount": 980}],
        )

        self.assertEqual(report["closure_reference"]["metrics"]["operational_income_total"], 1000)
        self.assertEqual(report["operation_totals"]["operational_income_total"], 980)
        self.assertEqual(report["discrepancy"]["status"], "delta")
        self.assertEqual(report["discrepancy"]["metrics"]["operational_income_total"], -20)

    def test_audit_inventory_uses_existing_sources_and_marks_history_limits(self):
        inventory = build_audit_inventory(period_id="closure:44")

        self.assertEqual(inventory["period_id"], "closure:44")
        self.assertIn("closures", inventory["available_sources"])
        self.assertIn("operational_rows", inventory["available_sources"])
        self.assertIn({"source": "print_jobs", "state": "partial"}, inventory["coverage"])
        self.assertEqual(inventory["unavailable_history"], ["before_first_closure", "after_current_rows"])
        self.assertFalse(inventory["requires_event_sourcing"])

    @patch("app.repositories.reporting_repo.db_conn")
    def test_repository_audit_inventory_exposes_plate_history_source_states(self, db_conn):
        from app.repositories.reporting_repo import get_audit_inventory

        db_conn.return_value = nullcontext(
            _AuditInventoryConnection(
                unavailable_tables={"ingresos_eliminados"},
                empty_tables={"operaciones_servicio"},
            )
        )

        inventory = get_audit_inventory("closure:44")

        coverage = {item["source"]: item["state"] for item in inventory["coverage"]}
        self.assertEqual(coverage["parking"], "available")
        self.assertEqual(coverage["solo_wash"], "partial")
        self.assertEqual(coverage["monthly_payment"], "available")
        self.assertEqual(coverage["night_charge"], "available")
        self.assertEqual(coverage["closure"], "available")
        self.assertEqual(coverage["logical_deletion"], "unavailable")

    @patch("app.repositories.reporting_repo.db_conn")
    def test_repository_closed_report_includes_mensualidades_and_active_monthly_capacity(self, db_conn):
        from app.repositories.reporting_repo import get_closed_report

        closure_result = MagicMock()
        closure_result.mappings.return_value.first.return_value = {
            "id_cierre": 80,
            "fecha_inicio": datetime(2026, 9, 28, 9, 30),
            "fecha_cierre": datetime(2026, 9, 29, 2, 0),
            "total_general": 1500,
            "total_mensualidades_monto": 300,
            "total_gastos": 100,
            "total_neto": 1400,
        }
        totals_result = MagicMock()
        totals_result.mappings.return_value.one.return_value = {
            "vehicle_count": 2,
            "parking_income": 1000,
            "bathroom_income": 100,
            "wash_income": 100,
            "night_income": 0,
            "expenses": 100,
            "mensualidades": 300,
        }
        active_monthly_result = MagicMock()
        active_monthly_result.scalar.return_value = 7
        conn = MagicMock()
        conn.execute.side_effect = [closure_result, totals_result, active_monthly_result]
        db_conn.return_value = nullcontext(conn)

        report = get_closed_report(80)

        self.assertEqual(report["operation_totals"]["operational_net_total"], 1400)
        self.assertEqual(report["operation_totals"]["net_revenue_total"], 1400)
        self.assertEqual(report["operation_totals"]["mensualidad_sales_total"], 300)
        self.assertEqual(report["operation_totals"]["monthly_payments_collected_total"], 300)
        self.assertEqual(report["operation_totals"]["collected_sources_total"], 1200)
        self.assertEqual(report["closure_reference"]["metrics"]["collected_sources_total"], 1200)
        self.assertEqual(report["capacity"]["reserved_monthly_spaces"], 7)
        self.assertEqual(report["capacity"]["effective_transient_capacity"], 43)

    @patch("app.repositories.reporting_repo.db_conn")
    def test_repository_closed_report_unknown_closure_fails_safely(self, db_conn):
        from app.repositories.reporting_repo import get_closed_report

        closure_result = MagicMock()
        closure_result.mappings.return_value.first.return_value = None
        conn = MagicMock()
        conn.execute.return_value = closure_result
        db_conn.return_value = nullcontext(conn)

        with self.assertRaisesRegex(LookupError, "CLOSURE_NOT_FOUND"):
            get_closed_report(999)

        conn.execute.assert_called_once()

    @patch("app.repositories.reporting_repo.db_conn")
    def test_repository_closed_report_uses_closure_timing_and_excludes_active_washes(self, db_conn):
        from app.repositories.reporting_repo import get_closed_report

        closure_result = MagicMock()
        closure_result.mappings.return_value.first.return_value = {
            "id_cierre": 81,
            "fecha_inicio": datetime(2026, 9, 28, 9, 30),
            "fecha_cierre": datetime(2026, 9, 29, 2, 0),
            "total_general": 1800,
            "total_mensualidades_monto": 500,
            "total_gastos": 200,
            "total_neto": 1600,
        }
        totals_result = MagicMock()
        totals_result.mappings.return_value.one.return_value = {
            "vehicle_count": 1,
            "parking_income": 1000,
            "bathroom_income": 100,
            "wash_income": 200,
            "night_income": 0,
            "expenses": 200,
            "mensualidades": 500,
        }
        active_monthly_result = MagicMock()
        active_monthly_result.scalar.return_value = 3
        conn = MagicMock()
        conn.execute.side_effect = [closure_result, totals_result, active_monthly_result]
        db_conn.return_value = nullcontext(conn)

        report = get_closed_report(81)
        totals_sql = str(conn.execute.call_args_list[1].args[0])

        self.assertIn("p.id_cierre = :id_cierre", totals_sql)
        self.assertIn("o.estado = 'FINALIZADO_COBRADO'", totals_sql)
        self.assertIn("o.id_ingreso_generado IS NULL", totals_sql)
        self.assertEqual(report["operation_totals"]["collected_sources_total"], 1300)
        self.assertEqual(report["operation_totals"]["monthly_payments_collected_total"], 500)
        self.assertEqual(report["operation_totals"]["net_revenue_total"], 1600)

    @patch("app.repositories.reporting_repo.db_conn")
    def test_repository_closed_period_operation_rows_lookup_closure_and_return_metadata(self, db_conn):
        from app.repositories.reporting_repo import get_closed_period_operation_rows

        closure_result = MagicMock()
        closure_result.mappings.return_value.first.return_value = {
            "id_cierre": 18,
            "fecha_inicio": datetime(2026, 9, 28, 9, 30),
            "fecha_cierre": datetime(2026, 9, 29, 2, 0),
        }
        count_result = MagicMock()
        count_result.scalar.return_value = 3
        page_result = MagicMock()
        page_result.mappings.return_value.all.return_value = [
            {
                "source": "parking",
                "source_id": 10,
                "occurred_at": datetime(2026, 9, 28, 12, 0),
                "amount": 1500,
                "category": "parking",
                "operator": "operator-a",
                "plate": "ABC123",
                "description": "Parking exit",
            }
        ]
        conn = MagicMock()
        conn.execute.side_effect = [closure_result, count_result, page_result]
        db_conn.return_value = nullcontext(conn)

        result = get_closed_period_operation_rows(
            18,
            filters={"category": "parking", "operator": "operator-a", "plate": "ABC123"},
            sort={"field": "amount", "direction": "desc", "tie_breaker": "operation_id"},
            pagination={"limit": 2, "offset": 0},
        )

        self.assertEqual(result["period_id"], "closure:18")
        self.assertEqual(result["filters"]["plate"], "ABC123")
        self.assertEqual(result["pagination"], {"total": 3, "limit": 2, "offset": 0, "has_more": True, "next_offset": 2})
        self.assertEqual(result["items"][0]["operation_id"], "parking:10")
        sql_text = "\n".join(str(call.args[0]) for call in conn.execute.call_args_list)
        self.assertIn("WHERE id_cierre = :id_cierre", sql_text)
        self.assertIn("FROM usos_bano", sql_text)
        self.assertIn("FROM operaciones_servicio", sql_text)
        self.assertIn("FROM cobros_noches", sql_text)
        self.assertIn("FROM pagos_mensuales", sql_text)
        self.assertIn("FROM gastos_operacion", sql_text)
        self.assertIn("ORDER BY amount DESC, source ASC, source_id ASC", sql_text)
        self.assertIn("LIMIT :limit OFFSET :offset", sql_text)
        params = conn.execute.call_args_list[-1].args[1]
        self.assertEqual(params["id_cierre"], 18)
        self.assertEqual(params["category"], "parking")
        self.assertEqual(params["operator"], "operator-a")
        self.assertEqual(params["plate"], "ABC123")
        self.assertEqual(params["limit"], 2)
        self.assertEqual(params["offset"], 0)

    @patch("app.repositories.reporting_repo.db_conn")
    def test_repository_closed_period_operation_rows_reports_final_page(self, db_conn):
        from app.repositories.reporting_repo import get_closed_period_operation_rows

        closure_result = MagicMock()
        closure_result.mappings.return_value.first.return_value = {
            "id_cierre": 18,
            "fecha_inicio": datetime(2026, 9, 28, 9, 30),
            "fecha_cierre": datetime(2026, 9, 29, 2, 0),
        }
        count_result = MagicMock()
        count_result.scalar.return_value = 3
        page_result = MagicMock()
        page_result.mappings.return_value.all.return_value = []
        conn = MagicMock()
        conn.execute.side_effect = [closure_result, count_result, page_result]
        db_conn.return_value = nullcontext(conn)

        result = get_closed_period_operation_rows(
            18,
            filters={},
            sort={"field": "occurred_at", "direction": "asc", "tie_breaker": "operation_id"},
            pagination={"limit": 2, "offset": 2},
        )

        self.assertFalse(result["pagination"]["has_more"])
        self.assertIsNone(result["pagination"]["next_offset"])

    @patch("app.repositories.reporting_repo.db_conn")
    def test_repository_closed_period_operation_rows_missing_closure_raises_lookup_error(self, db_conn):
        from app.repositories.reporting_repo import get_closed_period_operation_rows

        closure_result = MagicMock()
        closure_result.mappings.return_value.first.return_value = None
        conn = MagicMock()
        conn.execute.return_value = closure_result
        db_conn.return_value = nullcontext(conn)

        with self.assertRaisesRegex(LookupError, "CLOSURE_NOT_FOUND"):
            get_closed_period_operation_rows(
                999,
                filters={},
                sort={"field": "occurred_at", "direction": "asc", "tie_breaker": "operation_id"},
                pagination={"limit": 10, "offset": 0},
            )

class _AuditInventoryConnection:
    def __init__(self, unavailable_tables=None, empty_tables=None):
        self.unavailable_tables = set(unavailable_tables or [])
        self.empty_tables = set(empty_tables or [])

    def execute(self, statement):
        sql = str(statement)
        table_name = sql.rsplit("FROM ", 1)[1].strip()
        if table_name in self.unavailable_tables:
            raise RuntimeError("missing table")
        return _AuditInventoryResult(0 if table_name in self.empty_tables else 1)


class _AuditInventoryResult:
    def __init__(self, count):
        self.count = count

    def scalar(self):
        return self.count


if __name__ == "__main__":
    unittest.main()
