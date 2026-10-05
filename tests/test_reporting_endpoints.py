import inspect
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import HTTPException

from app.api.v1.endpoints import reporting


def _allowed_roles(function):
    for parameter in inspect.signature(function).parameters.values():
        dependency = getattr(parameter.default, "dependency", None)
        if hasattr(dependency, "allowed_roles"):
            return set(dependency.allowed_roles)
    return set()


class ReportingEndpointTests(unittest.TestCase):
    def test_dashboard_is_admin_only(self):
        self.assertEqual(_allowed_roles(reporting.get_dashboard), {"admin"})

    def test_unsupported_dashboard_filter_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            reporting.get_dashboard(unsupported_filter="ledger_balance")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "UNSUPPORTED_REPORTING_FILTER")

    def test_auditor_role_does_not_grant_reporting_access(self):
        self.assertEqual(_allowed_roles(reporting.get_dashboard), {"admin"})
        self.assertNotIn("auditor", _allowed_roles(reporting.get_dashboard))

    @patch("app.api.v1.endpoints.reporting.get_open_dashboard")
    def test_dashboard_returns_repository_backed_open_period(self, get_open_dashboard):
        get_open_dashboard.return_value = {
            "period": {"id": "open:8", "state": "open"},
            "metrics": {"operational_income_total": 2500},
        }

        result = reporting.get_dashboard()

        self.assertEqual(result["period"]["id"], "open:8")
        self.assertEqual(result["metrics"]["operational_income_total"], 2500)
        get_open_dashboard.assert_called_once_with()

    @patch("app.api.v1.endpoints.reporting.get_persisted_closed_report")
    def test_closed_report_uses_persisted_closure(self, get_closed_report):
        get_closed_report.return_value = {"report_id": "closed:18"}

        result = reporting.get_closed_report(18)

        self.assertEqual(result["report_id"], "closed:18")
        get_closed_report.assert_called_once_with(18)

    @patch("app.api.v1.endpoints.reporting.get_persisted_closed_report", side_effect=LookupError("CLOSURE_NOT_FOUND"))
    def test_missing_closed_report_is_not_fabricated(self, _get_closed_report):
        with self.assertRaises(HTTPException) as raised:
            reporting.get_closed_report(999)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "CLOSURE_NOT_FOUND")

    def test_closed_report_export_is_admin_only(self):
        self.assertEqual(_allowed_roles(reporting.export_closed_report), {"admin"})

    def test_audit_inventory_is_admin_only(self):
        self.assertEqual(_allowed_roles(reporting.get_audit_inventory), {"admin"})

    def test_plate_history_is_admin_only(self):
        self.assertEqual(_allowed_roles(reporting.get_plate_history), {"admin"})

    def test_plate_history_rejects_invalid_plate_before_repository_access(self):
        with patch("app.api.v1.endpoints.reporting.get_persisted_plate_history") as get_plate_history:
            with self.assertRaises(HTTPException) as raised:
                reporting.get_plate_history("not-a-plate", start="2026-01-01T00:00:00", end="2026-01-02T00:00:00")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "INVALID_PLATE")
        get_plate_history.assert_not_called()

    def test_plate_history_rejects_missing_or_invalid_bounds_before_repository_access(self):
        invalid_cases = [
            {"start": "", "end": "2026-01-02T00:00:00", "detail": "MISSING_HISTORY_BOUNDS"},
            {"start": "2026-01-02T00:00:00", "end": "2026-01-01T00:00:00", "detail": "INVALID_HISTORY_BOUNDS"},
            {"start": "not-a-date", "end": "2026-01-02T00:00:00", "detail": "INVALID_HISTORY_BOUNDS"},
        ]

        for case in invalid_cases:
            with self.subTest(case=case):
                with patch("app.api.v1.endpoints.reporting.get_persisted_plate_history") as get_plate_history:
                    with self.assertRaises(HTTPException) as raised:
                        reporting.get_plate_history("AB123CD", start=case["start"], end=case["end"])

                self.assertEqual(raised.exception.status_code, 422)
                self.assertEqual(raised.exception.detail, case["detail"])
                get_plate_history.assert_not_called()

    def test_plate_history_rejects_excessive_window_before_repository_access(self):
        with patch("app.api.v1.endpoints.reporting.get_persisted_plate_history") as get_plate_history:
            with self.assertRaises(HTTPException) as raised:
                reporting.get_plate_history("AB123CD", start="2026-01-01T00:00:00", end="2027-01-03T00:00:00")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "HISTORY_WINDOW_TOO_LARGE")
        get_plate_history.assert_not_called()

    def test_plate_history_rejects_limit_outside_allowed_range_before_repository_access(self):
        for limit in (0, 501):
            with self.subTest(limit=limit):
                with patch("app.api.v1.endpoints.reporting.get_persisted_plate_history") as get_plate_history:
                    with self.assertRaises(HTTPException) as raised:
                        reporting.get_plate_history(
                            "AB123CD",
                            start="2026-01-01T00:00:00",
                            end="2026-01-02T00:00:00",
                            limit=limit,
                        )

                self.assertEqual(raised.exception.status_code, 422)
                self.assertEqual(raised.exception.detail, "INVALID_HISTORY_LIMIT")
                get_plate_history.assert_not_called()

    @patch("app.api.v1.endpoints.reporting.get_persisted_plate_history")
    def test_plate_history_delegates_normalized_plate_parsed_bounds_and_limit(self, get_plate_history):
        get_plate_history.return_value = {"plate": "AB123CD", "timeline": []}

        result = reporting.get_plate_history(
            "ab 123 cd",
            start="2026-01-01T00:00:00",
            end="2026-01-02T00:00:00",
            limit=25,
        )

        self.assertEqual(result, {"plate": "AB123CD", "timeline": []})
        get_plate_history.assert_called_once_with(
            "AB123CD",
            start=datetime(2026, 1, 1, 0, 0),
            end=datetime(2026, 1, 2, 0, 0),
            limit=25,
        )

    @patch("app.api.v1.endpoints.reporting.get_persisted_plate_history", side_effect=ValueError("INVALID_SOURCE_BOUNDS"))
    def test_plate_history_repository_value_error_is_422(self, _get_plate_history):
        with self.assertRaises(HTTPException) as raised:
            reporting.get_plate_history("AB123CD", start="2026-01-01T00:00:00", end="2026-01-02T00:00:00")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "INVALID_SOURCE_BOUNDS")

    @patch("app.api.v1.endpoints.reporting.get_persisted_closed_report")
    @patch("app.api.v1.endpoints.reporting.build_report_export")
    def test_export_closed_report_uses_persisted_report_and_format(self, build_report_export, get_closed_report):
        get_closed_report.return_value = {"report_id": "closed:18"}
        build_report_export.return_value = {"format": "xlsx"}

        result = reporting.export_closed_report(18, "xlsx")

        self.assertEqual(result["format"], "xlsx")
        get_closed_report.assert_called_once_with(18)
        self.assertEqual(build_report_export.call_args.args[0], {"report_id": "closed:18"})
        self.assertEqual(build_report_export.call_args.args[1], "xlsx")

    @patch("app.api.v1.endpoints.reporting.build_report_export", side_effect=ValueError("UNSUPPORTED_EXPORT_FORMAT"))
    @patch("app.api.v1.endpoints.reporting.get_persisted_closed_report")
    def test_export_validation_errors_are_422(self, get_closed_report, _build_report_export):
        get_closed_report.return_value = {"report_id": "closed:18"}

        with self.assertRaises(HTTPException) as raised:
            reporting.export_closed_report(18, "json")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "UNSUPPORTED_EXPORT_FORMAT")

    @patch("app.api.v1.endpoints.reporting.get_persisted_closed_report", side_effect=LookupError("CLOSURE_NOT_FOUND"))
    def test_export_missing_closure_is_404(self, _get_closed_report):
        with self.assertRaises(HTTPException) as raised:
            reporting.export_closed_report(999, "pdf")

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "CLOSURE_NOT_FOUND")

    @patch("app.api.v1.endpoints.reporting.get_persisted_audit_inventory")
    def test_audit_inventory_uses_repository(self, get_audit_inventory):
        get_audit_inventory.return_value = {"period_id": "closure:18"}

        result = reporting.get_audit_inventory(period_id="closure:18")

        self.assertEqual(result["period_id"], "closure:18")
        get_audit_inventory.assert_called_once_with("closure:18")


if __name__ == "__main__":
    unittest.main()
