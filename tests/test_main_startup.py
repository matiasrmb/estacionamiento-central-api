import unittest
from unittest.mock import patch

from app import main
from app.db import schema_ensure


class MainStartupTests(unittest.TestCase):
    def test_startup_does_not_import_asistencias_schema_ensure(self):
        self.assertFalse(hasattr(schema_ensure, "ensure_asistencias_schema"))
        self.assertFalse(hasattr(main, "ensure_asistencias_schema"))

    def test_successful_startup_ensures_all_schemas(self):
        with patch.object(type(main.settings), "validate_runtime_safety") as validate, \
             patch.object(main, "ensure_wash_vehicle_type_schema") as ensure_wash, \
             patch.object(main, "ensure_gastos_operacion_schema") as ensure_expenses, \
             patch.object(main, "ensure_monthly_payments_schema") as ensure_monthly, \
             patch.object(main, "ensure_noches_schema") as ensure_noches:
            main.on_startup()

        validate.assert_called_once_with()
        ensure_wash.assert_called_once_with()
        ensure_expenses.assert_called_once_with()
        ensure_monthly.assert_called_once_with()
        ensure_noches.assert_called_once_with()

    def test_gastos_schema_failure_prevents_startup(self):
        with patch.object(type(main.settings), "validate_runtime_safety"), \
             patch.object(main, "ensure_wash_vehicle_type_schema"), \
             patch.object(main, "ensure_monthly_payments_schema"), \
             patch.object(main, "ensure_noches_schema"), \
             patch.object(main, "ensure_gastos_operacion_schema", side_effect=RuntimeError("GASTOS_SCHEMA_UNAVAILABLE")):
            with self.assertRaisesRegex(RuntimeError, "GASTOS_SCHEMA_UNAVAILABLE"):
                main.on_startup()


if __name__ == "__main__":
    unittest.main()
