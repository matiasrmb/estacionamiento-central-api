from datetime import datetime
from contextlib import nullcontext
import unittest
from unittest.mock import MagicMock, patch

from app.repositories.reporting_read_models import (
    build_capacity,
    build_historical_completeness,
    build_metric_catalog,
    build_operation_pagination_metadata,
    build_operational_periods,
    build_reporting_summary,
    serialize_operation_row,
    validate_operation_filters,
    validate_operation_pagination,
    validate_operation_sort,
)


class ReportingReadModelsTests(unittest.TestCase):
    def test_metric_catalog_uses_canonical_names_and_signs(self):
        catalog = build_metric_catalog()

        self.assertEqual(catalog["version"], "2026-09-29")
        metrics = {metric["name"]: metric for metric in catalog["metrics"]}
        self.assertEqual(metrics["operational_income_total"]["sign"], "positive")
        self.assertEqual(metrics["operational_expense_total"]["sign"], "positive_expense_negative_result")
        self.assertEqual(metrics["operational_net_total"]["sign"], "signed")
        self.assertEqual(metrics["mensualidad_sales_total"]["sign"], "positive")
        self.assertEqual(metrics["vehicle_movement_count"]["sign"], "count")
        self.assertNotIn("taxes", metrics)
        self.assertNotIn("commissions", metrics)

    def test_reporting_summary_calculates_net_and_complete_400_row_count(self):
        movements = [
            {
                "occurred_at": datetime(2026, 9, 28, 10, 0),
                "amount": 10,
                "kind": "vehicle_exit",
                "operator": "operator-a",
            }
            for _ in range(400)
        ]
        expenses = [
            {
                "occurred_at": datetime(2026, 9, 28, 15, 0),
                "amount": 150,
                "operator": "operator-a",
            }
        ]
        mensualidades = [
            {
                "occurred_at": datetime(2026, 9, 28, 16, 0),
                "amount": 2000,
                "operator": "operator-a",
            }
        ]

        summary = build_reporting_summary(
            period={
                "id": "open:2026-09-28T09:30:00",
                "start": datetime(2026, 9, 28, 9, 30),
                "end": datetime(2026, 9, 29, 2, 0),
                "state": "closed",
            },
            vehicle_movements=movements,
            expenses=expenses,
            mensualidades=mensualidades,
        )

        self.assertEqual(summary["metrics"]["operational_income_total"], 4000)
        self.assertEqual(summary["metrics"]["operational_expense_total"], 150)
        self.assertEqual(summary["metrics"]["operational_net_total"], 5850)
        self.assertEqual(summary["metrics"]["mensualidad_sales_total"], 2000)
        self.assertEqual(summary["metrics"]["vehicle_movement_count"], 400)
        self.assertEqual(summary["pagination"]["summary_row_count"], 400)

    def test_operational_periods_are_closure_to_closure_and_can_cross_midnight(self):
        periods = build_operational_periods(
            closures=[
                {"id": 10, "closed_at": datetime(2026, 9, 28, 9, 30)},
                {"id": 11, "closed_at": datetime(2026, 9, 29, 2, 0)},
            ],
            now=datetime(2026, 9, 29, 5, 0),
        )

        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[0]["id"], "closure:10:11")
        self.assertEqual(periods[0]["start"], datetime(2026, 9, 28, 9, 30))
        self.assertEqual(periods[0]["end"], datetime(2026, 9, 29, 2, 0))
        self.assertEqual(periods[0]["state"], "closed")
        self.assertEqual(periods[1]["id"], "open:11")
        self.assertEqual(periods[1]["start"], datetime(2026, 9, 29, 2, 0))
        self.assertEqual(periods[1]["end"], datetime(2026, 9, 29, 5, 0))
        self.assertEqual(periods[1]["state"], "open")

    def test_operator_session_filters_attribute_without_splitting_operational_period(self):
        period = {
            "id": "closure:20:21",
            "start": datetime(2026, 9, 28, 9, 30),
            "end": datetime(2026, 9, 28, 19, 30),
            "state": "closed",
        }
        sessions = [
            {
                "session_id": "session-a",
                "operator": "operator-a",
                "start": datetime(2026, 9, 28, 9, 30),
                "end": datetime(2026, 9, 28, 14, 30),
            },
            {
                "session_id": "session-b",
                "operator": "operator-b",
                "start": datetime(2026, 9, 28, 14, 30),
                "end": datetime(2026, 9, 28, 19, 30),
            },
        ]
        movements = [
            {"occurred_at": datetime(2026, 9, 28, 11, 0), "amount": 1000, "operator": "operator-a"},
            {"occurred_at": datetime(2026, 9, 28, 16, 0), "amount": 2000, "operator": "operator-b"},
        ]

        summary = build_reporting_summary(
            period=period,
            vehicle_movements=movements,
            operator_sessions=sessions,
            operator_session_id="session-b",
        )

        self.assertEqual(summary["period"]["id"], "closure:20:21")
        self.assertEqual(summary["period"]["start"], "2026-09-28T09:30:00")
        self.assertEqual(summary["period"]["end"], "2026-09-28T19:30:00")
        self.assertEqual(summary["filters"]["operator_session_id"], "session-b")
        self.assertEqual(summary["metrics"]["operational_income_total"], 2000)
        self.assertEqual(summary["metrics"]["vehicle_movement_count"], 1)

    @patch("app.repositories.reporting_repo.get_cierre_pendiente")
    @patch("app.repositories.reporting_repo.db_conn")
    def test_open_dashboard_uses_last_closure_as_period_boundary(self, db_conn, get_cierre_pendiente):
        from app.repositories.reporting_repo import get_open_dashboard

        get_cierre_pendiente.return_value = {
            "fecha_inicio": datetime(2026, 9, 28, 10, 0),
            "total_general": 1200,
            "total_mensualidades_monto": 200,
            "total_gastos": 150,
            "total_salidas": 4,
        }
        latest_closure = {"id_cierre": 7, "fecha_cierre": datetime(2026, 9, 28, 9, 30)}
        result = MagicMock()
        result.mappings.return_value.first.return_value = latest_closure
        conn = MagicMock()
        conn.execute.return_value = result
        db_conn.return_value = nullcontext(conn)

        dashboard = get_open_dashboard()

        self.assertEqual(dashboard["period"]["id"], "open:7")
        self.assertEqual(dashboard["period"]["start"], "2026-09-28T09:30:00")
        self.assertEqual(dashboard["metrics"]["operational_income_total"], 1000)
        self.assertEqual(dashboard["metrics"]["operational_net_total"], 1050)

    def test_capacity_resolves_active_monthly_reserved_spaces(self):
        capacity = build_capacity(active_monthly_customers=12)

        self.assertEqual(capacity["total_spaces"], 50)
        self.assertEqual(capacity["reserved_monthly_spaces"], 12)
        self.assertEqual(capacity["effective_transient_capacity"], 38)
        self.assertEqual(capacity["source_state"], "resolved")

    def test_capacity_marks_unavailable_without_active_monthly_source(self):
        capacity = build_capacity()

        self.assertEqual(capacity["total_spaces"], 50)
        self.assertIsNone(capacity["effective_transient_capacity"])
        self.assertEqual(capacity["source_state"], "unavailable")
        self.assertEqual(capacity["unavailable_inputs"], ["active_monthly_customers"])

    def test_historical_completeness_rejects_unknown_status(self):
        partial = build_historical_completeness(
            "partial",
            missing_ranges=["before_first_closure"],
            unavailable_inputs=["legacy_daily_rows"],
        )

        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["missing_ranges"], ["before_first_closure"])
        with self.assertRaises(ValueError):
            build_historical_completeness("unknown")

    def test_operation_pagination_metadata_reports_next_page(self):
        pagination = build_operation_pagination_metadata(total=25, limit=10, offset=0)

        self.assertEqual(
            pagination,
            {
                "total": 25,
                "limit": 10,
                "offset": 0,
                "has_more": True,
                "next_offset": 10,
            },
        )

    def test_operation_pagination_metadata_reports_final_page(self):
        pagination = build_operation_pagination_metadata(total=25, limit=10, offset=20)

        self.assertEqual(pagination["total"], 25)
        self.assertEqual(pagination["limit"], 10)
        self.assertEqual(pagination["offset"], 20)
        self.assertFalse(pagination["has_more"])
        self.assertIsNone(pagination["next_offset"])

    def test_operation_pagination_rejects_out_of_bounds_values(self):
        self.assertEqual(validate_operation_pagination(limit=None, offset=None), {"limit": 100, "offset": 0})
        self.assertEqual(validate_operation_pagination(limit="200", offset="5"), {"limit": 200, "offset": 5})

        invalid_cases = [
            {"limit": "0", "offset": "0"},
            {"limit": "201", "offset": "0"},
            {"limit": "abc", "offset": "0"},
            {"limit": "10", "offset": "-1"},
            {"limit": "10", "offset": "abc"},
        ]
        for values in invalid_cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    validate_operation_pagination(**values)

    def test_operation_filters_accept_only_documented_keys_and_values(self):
        filters = validate_operation_filters(
            {
                "category": "vehicle_movement",
                "operator": "operator-a",
                "plate": "ABC123",
            }
        )

        self.assertEqual(filters["category"], "vehicle_movement")
        self.assertEqual(filters["operator"], "operator-a")
        self.assertEqual(filters["plate"], "ABC123")

        invalid_cases = [
            {"unknown": "value"},
            {"category": "unsupported"},
            {"operator": ""},
            {"plate": "   "},
        ]
        for filters in invalid_cases:
            with self.subTest(filters=filters):
                with self.assertRaises(ValueError):
                    validate_operation_filters(filters)

    def test_operation_sort_accepts_allow_list_and_tie_breaker(self):
        self.assertEqual(
            validate_operation_sort(sort=None, direction=None),
            {"field": "occurred_at", "direction": "asc", "tie_breaker": "operation_id"},
        )
        self.assertEqual(
            validate_operation_sort(sort="amount", direction="desc"),
            {"field": "amount", "direction": "desc", "tie_breaker": "operation_id"},
        )

        invalid_cases = [
            {"sort": "operator", "direction": "asc"},
            {"sort": "amount", "direction": "sideways"},
        ]
        for values in invalid_cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    validate_operation_sort(**values)

    def test_operation_row_serialization_uses_stable_operation_identity(self):
        row = serialize_operation_row(
            {
                "source": "vehicle_movement",
                "source_id": 123,
                "occurred_at": datetime(2026, 9, 28, 10, 30),
                "amount": "1500",
                "category": "vehicle_movement",
                "operator": "operator-a",
                "plate": "ABC123",
                "description": "Vehicle exit",
            }
        )

        self.assertEqual(row["operation_id"], "vehicle_movement:123")
        self.assertEqual(row["occurred_at"], "2026-09-28T10:30:00")
        self.assertEqual(row["amount"], 1500)
        self.assertEqual(row["category"], "vehicle_movement")
        self.assertEqual(row["operator"], "operator-a")
        self.assertEqual(row["plate"], "ABC123")
        self.assertEqual(row["description"], "Vehicle exit")


if __name__ == "__main__":
    unittest.main()
