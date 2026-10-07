import unittest

from app.repositories.accounting_contracts import build_accounting_summary, build_report_totals


class AccountingReportContractsTests(unittest.TestCase):
    def test_parking_wash_revenue_stays_inside_parking_total(self):
        summary = build_accounting_summary(
            parking_movements=[{"tarifa_aplicada": 1200}],
            bathroom_uses=[{"monto": 300}],
            wash_only_operations=[],
        )

        self.assertEqual(summary["total_recaudado"], 1200)
        self.assertEqual(summary["total_lavados_solos"], 0)
        self.assertEqual(summary["total_lavados_solos_monto"], 0)
        self.assertEqual(summary["total_general"], 1500)

    def test_charge_now_wash_only_revenue_is_separate_and_in_total_general(self):
        summary = build_accounting_summary(
            parking_movements=[{"tarifa_aplicada": 1200}],
            bathroom_uses=[{"monto": 300}],
            wash_only_operations=[
                {"estado": "FINALIZADO_COBRADO", "valor_lavado_snapshot": 8000},
                {"estado": "ACTIVO", "valor_lavado_snapshot": 9000},
            ],
        )

        self.assertEqual(summary["total_recaudado"], 1200)
        self.assertEqual(summary["total_lavados_solos"], 1)
        self.assertEqual(summary["total_lavados_solos_monto"], 8000)
        self.assertEqual(summary["total_general"], 9500)

    def test_wash_then_stay_defers_wash_revenue_until_parking_exit(self):
        summary = build_accounting_summary(
            parking_movements=[{"tarifa_aplicada": 10000}],
            bathroom_uses=[],
            wash_only_operations=[
                {"estado": "COBRADO_EN_SALIDA", "valor_lavado_snapshot": 8000},
            ],
        )

        self.assertEqual(summary["total_recaudado"], 10000)
        self.assertEqual(summary["total_lavados_solos"], 0)
        self.assertEqual(summary["total_lavados_solos_monto"], 0)
        self.assertEqual(summary["total_general"], 10000)

    def test_prepaid_nights_are_separate_from_exit_revenue_and_in_gross_total(self):
        summary = build_accounting_summary(
            parking_movements=[{"tarifa_aplicada": 1200}],
            bathroom_uses=[],
            wash_only_operations=[],
            night_charges=[{"monto_snapshot": 5000}],
        )

        self.assertEqual(summary["total_recaudado"], 1200)
        self.assertEqual(summary["total_noches"], 1)
        self.assertEqual(summary["total_noches_monto"], 5000)
        self.assertEqual(summary["total_general"], 6200)

    def test_report_totals_include_bathrooms_expenses_and_net(self):
        summary = build_report_totals(
            parking_movements=[{"tarifa_aplicada": 1200}],
            bathroom_uses=[{"monto": 300}],
            wash_only_operations=[{"estado": "FINALIZADO_COBRADO", "valor_lavado_snapshot": 800}],
            expenses=[{"monto": 500}],
            monthly_payments=[{"monto_snapshot": 2000}],
            night_charges=[{"monto_snapshot": 1000}],
        )

        self.assertEqual(summary["total_general"], 5300)
        self.assertEqual(summary["total_gastos"], 500)
        self.assertEqual(summary["total_neto"], 4800)
        self.assertEqual(summary["collected_sources_total"], 3300)
        self.assertEqual(summary["monthly_payments_collected_total"], 2000)
        self.assertEqual(summary["operational_expense_total"], 500)
        self.assertEqual(summary["net_revenue_total"], 4800)
        self.assertEqual(summary["operational_income_total"], 3300)
        self.assertEqual(summary["mensualidad_sales_total"], 2000)
        self.assertEqual(summary["operational_net_total"], 4800)

    def test_report_totals_include_charged_solo_wash_and_exclude_active_wash(self):
        summary = build_report_totals(
            parking_movements=[],
            bathroom_uses=[],
            wash_only_operations=[
                {"estado": "FINALIZADO_COBRADO", "valor_lavado_snapshot": 800},
                {"estado": "ACTIVO", "valor_lavado_snapshot": 900},
            ],
        )

        self.assertEqual(summary["total_lavados_solos"], 1)
        self.assertEqual(summary["total_lavados_solos_monto"], 800)
        self.assertEqual(summary["collected_sources_total"], 800)
        self.assertEqual(summary["net_revenue_total"], 800)


if __name__ == "__main__":
    unittest.main()
