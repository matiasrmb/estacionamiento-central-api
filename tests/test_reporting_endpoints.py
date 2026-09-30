import inspect
import unittest
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


if __name__ == "__main__":
    unittest.main()
