import inspect
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.endpoints import reporting


def _allowed_roles(function):
    for parameter in inspect.signature(function).parameters.values():
        dependency = getattr(parameter.default, "dependency", None)
        if hasattr(dependency, "allowed_roles"):
            return set(dependency.allowed_roles)
    return set()


def _request(query_string=""):
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": query_string.encode()})


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

    def test_operations_report_is_admin_only(self):
        self.assertEqual(_allowed_roles(reporting.get_operations_report), {"admin"})

    @patch("app.api.v1.endpoints.reporting.list_persisted_operation_rows")
    def test_operations_report_accepts_closure_period_and_delegates(self, list_operation_rows):
        list_operation_rows.return_value = {
            "period_id": "closure:18",
            "filters": {"category": "vehicle_movement", "plate": "ABC123"},
            "sort": {"field": "amount", "direction": "desc", "tie_breaker": "operation_id"},
            "pagination": {"total": 1, "limit": 25, "offset": 0, "has_more": False, "next_offset": None},
            "items": [],
        }

        result = reporting.get_operations_report(
            _request("period_id=closure:18&category=vehicle_movement&plate=ABC123&sort=amount&direction=desc&limit=25&offset=0"),
            period_id="closure:18",
            category="vehicle_movement",
            plate="ABC123",
            sort="amount",
            direction="desc",
            limit="25",
            offset="0",
        )

        self.assertEqual(result["period_id"], "closure:18")
        list_operation_rows.assert_called_once_with(
            18,
            filters={"category": "vehicle_movement", "plate": "ABC123"},
            sort={"field": "amount", "direction": "desc", "tie_breaker": "operation_id"},
            pagination={"limit": 25, "offset": 0},
        )

    def test_operations_report_rejects_non_closure_period(self):
        with self.assertRaises(HTTPException) as raised:
            reporting.get_operations_report(_request("period_id=open:current"), period_id="open:current")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "UNSUPPORTED_OPERATION_PERIOD")

    def test_operations_report_rejects_unknown_query_key(self):
        with self.assertRaises(HTTPException) as raised:
            reporting.get_operations_report(_request("period_id=closure:18&ledger=true"), period_id="closure:18")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "UNSUPPORTED_OPERATION_QUERY")

    def test_operations_report_validation_errors_are_422(self):
        with self.assertRaises(HTTPException) as raised:
            reporting.get_operations_report(
                _request("period_id=closure:18&sort=operator"),
                period_id="closure:18",
                sort="operator",
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "UNSUPPORTED_OPERATION_SORT")

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
