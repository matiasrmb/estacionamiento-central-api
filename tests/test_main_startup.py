import inspect
import unittest
from unittest.mock import patch

from app import main
from app.db import schema_ensure


class MainStartupTests(unittest.TestCase):
    def test_startup_does_not_import_asistencias_schema_ensure(self):
        self.assertFalse(hasattr(schema_ensure, "ensure_asistencias_schema"))
        self.assertFalse(hasattr(main, "ensure_asistencias_schema"))

    def test_runtime_does_not_expose_wash_vehicle_type_schema_ensure(self):
        self.assertFalse(hasattr(schema_ensure, "ensure_wash_vehicle_type_schema"))
        self.assertFalse(hasattr(schema_ensure, "_ensure_wash_vehicle_type_schema_on_connection"))
        self.assertFalse(hasattr(main, "ensure_wash_vehicle_type_schema"))

    def test_startup_does_not_import_noches_schema_ensure(self):
        self.assertFalse(hasattr(schema_ensure, "ensure_noches_schema"))
        self.assertFalse(hasattr(schema_ensure, "_ensure_noches_schema_on_connection"))
        self.assertFalse(hasattr(main, "ensure_noches_schema"))

    def test_runtime_does_not_expose_monthly_payments_schema_ensure(self):
        self.assertFalse(hasattr(schema_ensure, "ensure_monthly_payments_schema"))
        self.assertFalse(hasattr(schema_ensure, "_ensure_monthly_payments_schema_on_connection"))
        self.assertFalse(hasattr(main, "ensure_monthly_payments_schema"))
        source = inspect.getsource(schema_ensure).casefold()
        for monthly_ddl in ("pagos_mensuales", "dia_vencimiento", "total_mensualidades", "metodo_pago varchar(40)"):
            self.assertNotIn(monthly_ddl, source)

    def test_runtime_does_not_expose_gastos_cierres_banos_schema_ensure(self):
        self.assertFalse(hasattr(schema_ensure, "ensure_gastos_operacion_schema"))
        self.assertFalse(hasattr(schema_ensure, "_ensure_gastos_operacion_schema_on_connection"))
        self.assertFalse(hasattr(main, "ensure_gastos_operacion_schema"))
        source = inspect.getsource(schema_ensure).casefold()
        for runtime_ddl in ("gastos_operacion", "cierres_diarios", "usos_bano", "create table", "alter table", "create index"):
            self.assertNotIn(runtime_ddl, source)

    def test_successful_startup_only_validates_runtime_safety(self):
        with patch.object(type(main.settings), "validate_runtime_safety") as validate:
            main.on_startup()

        validate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
