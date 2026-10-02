from datetime import datetime
from contextlib import nullcontext
import unittest
from unittest.mock import MagicMock, patch

from app.repositories.reporting_read_models import build_audit_inventory, build_closed_report


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
        self.assertEqual(report["historical_completeness"]["status"], "complete")
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
        self.assertEqual(report["operation_totals"]["mensualidad_sales_total"], 300)
        self.assertEqual(report["capacity"]["reserved_monthly_spaces"], 7)
        self.assertEqual(report["capacity"]["effective_transient_capacity"], 43)


if __name__ == "__main__":
    unittest.main()
