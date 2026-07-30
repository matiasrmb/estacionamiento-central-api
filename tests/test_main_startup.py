import unittest
from unittest.mock import patch

from app import main


class MainStartupTests(unittest.TestCase):
    def test_gastos_schema_failure_prevents_startup(self):
        with patch.object(type(main.settings), "validate_runtime_safety"), \
             patch.object(main, "ensure_wash_vehicle_type_schema"), \
             patch.object(main, "ensure_operaciones_servicio_schema"), \
             patch.object(main, "ensure_gastos_operacion_schema", side_effect=RuntimeError("GASTOS_SCHEMA_UNAVAILABLE")):
            with self.assertRaisesRegex(RuntimeError, "GASTOS_SCHEMA_UNAVAILABLE"):
                main.on_startup()


if __name__ == "__main__":
    unittest.main()
