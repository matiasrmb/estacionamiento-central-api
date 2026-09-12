import unittest
from pathlib import Path

from app.api.v1.endpoints import resumen_turno
from app.db import schema_ensure
from app.repositories import cierres_repo


class NochesSchemaTests(unittest.TestCase):
    def test_runtime_does_not_expose_noches_schema_ensure(self):
        self.assertFalse(hasattr(schema_ensure, "ensure_noches_schema"))
        self.assertFalse(hasattr(schema_ensure, "_ensure_noches_schema_on_connection"))

    def test_runtime_schema_ensure_contains_no_noches_ddl_or_seed(self):
        source = Path(schema_ensure.__file__).read_text(encoding="utf-8")

        self.assertNotIn("cobros_noches", source)
        self.assertNotIn("noches_activo", source)
        self.assertNotIn("total_noches", source)

    def test_cierre_and_resumen_runtime_paths_do_not_ensure_noches_schema(self):
        for module in (cierres_repo, resumen_turno):
            source = Path(module.__file__).read_text(encoding="utf-8")

            self.assertNotIn("ensure_noches_schema", source)
            self.assertNotIn("_ensure_noches_schema_on_connection", source)
            self.assertNotIn("CREATE TABLE IF NOT EXISTS cobros_noches", source)
            self.assertNotIn("ALTER TABLE cobros_noches", source)
            self.assertNotIn("noches_activo", source)


if __name__ == "__main__":
    unittest.main()
