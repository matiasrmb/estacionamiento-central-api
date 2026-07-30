import unittest

from app.repositories.accounting_contracts import build_accounting_summary


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


if __name__ == "__main__":
    unittest.main()
