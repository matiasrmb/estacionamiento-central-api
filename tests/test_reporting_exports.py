from datetime import datetime
import unittest

from app.repositories.reporting_read_models import build_closed_report, build_historical_completeness, build_report_export


class ReportingExportTests(unittest.TestCase):
    def test_csv_export_remains_legacy_only_with_reproducibility_metadata(self):
        report = _closed_report()

        export = build_report_export(report, "csv", generated_at=datetime(2026, 9, 29, 3, 0))

        self.assertEqual(export["content_type"], "text/csv")
        self.assertEqual(export["metadata"]["compatibility"], "legacy-only")
        self.assertIn("report_id,closed:50", export["content"])
        self.assertIn("closure_reference_id,50", export["content"])
        self.assertIn("generated_at,2026-09-29T03:00:00", export["content"])
        self.assertIn("metric_catalog_version,2026-09-29", export["content"])
        self.assertIn("source_state,closed_snapshot_with_operational_drill_down", export["content"])

    def test_pdf_export_has_stable_closed_report_content(self):
        report = _closed_report()
        generated_at = datetime(2026, 9, 29, 3, 0)

        first = build_report_export(report, "pdf", generated_at=generated_at)
        second = build_report_export(report, "pdf", generated_at=generated_at)

        self.assertEqual(first["content_type"], "application/pdf")
        self.assertEqual(first["metadata"]["compatibility"], "canonical")
        self.assertEqual(first["content"], second["content"])
        self.assertIn("Report ID: closed:50", first["content"])
        self.assertIn("Closure Reference ID: 50", first["content"])
        self.assertIn("Operational Income Total: 1000", first["content"])

    def test_xlsx_export_has_same_identity_totals_and_completeness_metadata(self):
        report = _closed_report(
            historical_completeness=build_historical_completeness(
                "partial",
                missing_ranges=["before_first_closure"],
                unavailable_inputs=["legacy_daily_rows"],
            )
        )

        export = build_report_export(report, "xlsx", generated_at=datetime(2026, 9, 29, 3, 0))

        self.assertEqual(export["format"], "xlsx")
        self.assertEqual(
            export["content_type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(export["metadata"]["report_id"], "closed:50")
        self.assertEqual(export["metadata"]["historical_completeness"]["status"], "partial")
        self.assertEqual(export["metadata"]["totals"]["operational_net_total"], 900)
        self.assertIn("completeness\tpartial", export["content"])

    def test_export_rejects_unsupported_format(self):
        with self.assertRaises(ValueError) as raised:
            build_report_export(_closed_report(), "json", generated_at=datetime(2026, 9, 29, 3, 0))

        self.assertEqual(str(raised.exception), "UNSUPPORTED_EXPORT_FORMAT")


def _closed_report(historical_completeness=None):
    return build_closed_report(
        closure={
            "id": 50,
            "period_start": datetime(2026, 9, 28, 9, 30),
            "closed_at": datetime(2026, 9, 29, 2, 0),
            "operational_income_total": 1000,
            "operational_expense_total": 100,
            "mensualidad_sales_total": 0,
        },
        vehicle_movements=[{"id": 7, "occurred_at": datetime(2026, 9, 28, 10, 0), "amount": 1000}],
        expenses=[{"id": 4, "occurred_at": datetime(2026, 9, 28, 11, 0), "amount": 100}],
        historical_completeness=historical_completeness,
    )


if __name__ == "__main__":
    unittest.main()
