from datetime import datetime
from contextlib import nullcontext
import unittest
from unittest.mock import MagicMock, patch

from app.repositories.reporting_read_models import (
    PLATE_HISTORY_SOURCES,
    build_audit_inventory,
    build_plate_history_response,
    build_capacity,
    build_historical_completeness,
    build_metric_catalog,
    build_operational_periods,
    build_reporting_summary,
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

    def test_audit_inventory_exposes_plate_history_source_coverage(self):
        inventory = build_audit_inventory(period_id="closure:44")

        coverage = {item["source"]: item["state"] for item in inventory["coverage"]}
        for source in PLATE_HISTORY_SOURCES:
            self.assertIn(source, coverage)
            self.assertEqual(coverage[source], "available")

    def test_audit_inventory_marks_unavailable_plate_history_sources(self):
        inventory = build_audit_inventory(
            period_id="closure:44",
            coverage={
                "parking": "available",
                "solo_wash": "partial",
                "monthly_payment": "available",
                "night_charge": "unavailable",
                "closure": "available",
                "logical_deletion": "unavailable",
            },
        )

        coverage = {item["source"]: item["state"] for item in inventory["coverage"]}
        self.assertEqual(coverage["solo_wash"], "partial")
        self.assertEqual(coverage["night_charge"], "unavailable")
        self.assertEqual(coverage["logical_deletion"], "unavailable")
        self.assertIn("solo_wash", inventory["available_sources"])
        self.assertIn("night_charge", inventory["unavailable_sources"])
        self.assertIn("logical_deletion", inventory["unavailable_sources"])

    def test_audit_inventory_keeps_persisted_anomalies_and_event_sourcing_out_of_scope(self):
        inventory = build_audit_inventory(period_id="closure:44")

        self.assertFalse(inventory["requires_event_sourcing"])
        self.assertEqual(
            inventory["unsupported_behaviors"],
            [
                "persisted_anomaly_records",
                "event_sourced_history",
                "transversal_audit_log",
            ],
        )

    def test_plate_history_orders_timeline_and_preserves_source_labels(self):
        response = build_plate_history_response(
            plate="ab 123 cd",
            bounds={"start": datetime(2026, 1, 1), "end": datetime(2026, 1, 2), "limit": 500},
            rows=[
                {
                    "id": 2,
                    "source": "solo_wash",
                    "occurred_at": datetime(2026, 1, 1, 10, 0),
                    "amount": 200,
                },
                {
                    "id": 3,
                    "source": "parking",
                    "occurred_at": datetime(2026, 1, 1, 10, 0),
                    "amount": 1000,
                    "closure_id": 18,
                },
                {
                    "id": 1,
                    "source": "monthly_payment",
                    "period": "2026-01",
                    "amount": 3000,
                },
            ],
            coverage={
                "parking": "available",
                "solo_wash": "available",
                "monthly_payment": "available",
                "night_charge": "unavailable",
            },
        )

        self.assertEqual(response["plate"], "AB123CD")
        self.assertEqual(
            [(row["source"], row.get("id")) for row in response["timeline"]],
            [("monthly_payment", 1), ("parking", 3), ("solo_wash", 2)],
        )
        self.assertEqual(response["timeline"][1]["occurred_at"], "2026-01-01T10:00:00")
        self.assertEqual(response["timeline"][1]["closure_id"], 18)

    def test_plate_history_statistics_coverage_and_weakest_completeness(self):
        response = build_plate_history_response(
            plate="AB123CD",
            bounds={"start": datetime(2026, 1, 1), "end": datetime(2026, 1, 2), "limit": 500},
            rows=[
                {"source": "parking", "occurred_at": datetime(2026, 1, 1, 10, 0), "amount": 1000},
                {"source": "monthly_payment", "period": "2026-01", "amount": 3000},
            ],
            coverage={"parking": "available", "monthly_payment": "partial", "night_charge": "unavailable"},
        )

        self.assertEqual(response["statistics"]["timeline_row_count"], 2)
        self.assertEqual(response["statistics"]["total_amount"], 4000)
        self.assertEqual(response["statistics"]["sources_with_rows"], ["monthly_payment", "parking"])
        self.assertEqual(
            response["source_coverage"],
            [
                {"source": "monthly_payment", "state": "partial"},
                {"source": "night_charge", "state": "unavailable"},
                {"source": "parking", "state": "available"},
            ],
        )
        self.assertEqual(response["historical_completeness"]["status"], "unavailable")
        self.assertEqual(response["historical_completeness"]["unavailable_inputs"], ["night_charge"])
        self.assertEqual(
            response["anomaly_summary"],
            [
                {"code": "source_partial", "sources": ["monthly_payment"], "severity": "info"},
                {"code": "source_unavailable", "sources": ["night_charge"], "severity": "info"},
            ],
        )

    @patch("app.repositories.reporting_repo.db_conn")
    def test_plate_history_repository_returns_source_rows_without_fabricating_missing_evidence(self, db_conn):
        from app.repositories.reporting_repo import get_plate_history

        conn = _PlateHistoryConnection(
            {
                "FROM cierres_diarios": [],
                "FROM ingresos i": [
                    {
                        "id": 10,
                        "plate": "AB123CD",
                        "occurred_at": datetime(2026, 1, 1, 10, 0),
                        "amount": 1000,
                        "closure_id": 18,
                    }
                ],
                "FROM operaciones_servicio": [],
                "FROM pagos_mensuales": [
                    {
                        "id": 20,
                        "plate": "AB123CD",
                        "occurred_at": datetime(2026, 1, 1, 9, 0),
                        "period": "2026-01",
                        "amount": 3000,
                    }
                ],
                "FROM cobros_noches": [],
                "FROM ingresos_eliminados": [],
            }
        )
        db_conn.return_value = nullcontext(conn)

        response = get_plate_history("AB123CD", datetime(2026, 1, 1), datetime(2026, 1, 2), limit=500)

        self.assertEqual(response["plate"], "AB123CD")
        self.assertEqual(response["statistics"]["timeline_row_count"], 2)
        self.assertEqual(response["statistics"]["sources_with_rows"], ["monthly_payment", "parking"])
        self.assertEqual({item["source"]: item["state"] for item in response["source_coverage"]}, {
            "parking": "available",
            "solo_wash": "available",
            "monthly_payment": "available",
            "night_charge": "available",
            "closure": "available",
            "logical_deletion": "available",
        })
        self.assertNotIn("night_charge", response["statistics"]["sources_with_rows"])
        self.assertEqual(response["historical_completeness"]["status"], "complete")

    @patch("app.repositories.reporting_repo.db_conn")
    def test_plate_history_repository_marks_unavailable_sources_without_fabricated_rows(self, db_conn):
        from app.repositories.reporting_repo import get_plate_history

        conn = _PlateHistoryConnection(
            {
                "FROM ingresos i": [],
                "FROM operaciones_servicio": [],
                "FROM pagos_mensuales": [],
                "FROM cobros_noches": RuntimeError("missing table"),
                "FROM cierres_diarios": [],
                "FROM ingresos_eliminados": RuntimeError("missing table"),
            }
        )
        db_conn.return_value = nullcontext(conn)

        response = get_plate_history("AB123CD", datetime(2026, 1, 1), datetime(2026, 1, 2), limit=500)

        coverage = {item["source"]: item["state"] for item in response["source_coverage"]}
        self.assertEqual(coverage["night_charge"], "unavailable")
        self.assertEqual(coverage["logical_deletion"], "unavailable")
        self.assertEqual(response["timeline"], [])
        self.assertEqual(response["historical_completeness"]["status"], "unavailable")
        self.assertEqual(
            response["historical_completeness"]["unavailable_inputs"],
            ["logical_deletion", "night_charge"],
        )


class _PlateHistoryConnection:
    def __init__(self, results_by_fragment):
        self.results_by_fragment = results_by_fragment

    def execute(self, statement, _params=None):
        sql = str(statement)
        for fragment, result in self.results_by_fragment.items():
            if fragment in sql:
                if isinstance(result, Exception):
                    raise result
                return _PlateHistoryResult(result)
        raise AssertionError(f"Unexpected SQL: {sql}")


class _PlateHistoryResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


if __name__ == "__main__":
    unittest.main()
