from datetime import datetime
import unittest

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
        self.assertEqual(report["operation_drill_down"][0]["canonical_category"], "vehicle_movement")
        self.assertEqual(report["discrepancy"]["status"], "none")

    def test_closed_report_shows_delta_discrepancy_without_rewriting_closure(self):
        report = build_closed_report(
            closure={
                "id": 45,
                "period_start": datetime(2026, 9, 28, 9, 30),
                "closed_at": datetime(2026, 9, 29, 2, 0),
                "operational_income_total": 1000,
                "operational_expense_total": 0,
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
        self.assertEqual(inventory["unavailable_history"], ["before_first_closure", "after_current_rows"])
        self.assertFalse(inventory["requires_event_sourcing"])


if __name__ == "__main__":
    unittest.main()
