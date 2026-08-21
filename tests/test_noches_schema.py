import unittest
from pathlib import Path

from app.db.schema_ensure import _ensure_noches_schema_on_connection


class NochesSchemaTests(unittest.TestCase):
    def test_migration_declares_prepaid_charge_snapshots_and_close_link(self):
        migration = Path(__file__).resolve().parents[1].joinpath(
            "app", "db", "migrations", "006_cobros_noches.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS cobros_noches", migration)
        self.assertIn("monto_snapshot INT NOT NULL", migration)
        self.assertIn("hora_inicio_snapshot TIME NOT NULL", migration)
        self.assertIn("hora_fin_snapshot TIME NOT NULL", migration)
        self.assertIn("fecha_hora_pago DATETIME NOT NULL", migration)
        self.assertIn("id_cierre INT NULL", migration)
        self.assertIn("estado_operativo ENUM('PENDIENTE', 'RETIRADO', 'CONVERTIDO')", migration)
        self.assertIn("'noches_activo', '0'", migration)

    def test_runtime_ensure_creates_charge_table_and_default_configuration(self):
        class FakeConn:
            def __init__(self):
                self.statements = []

            def execute(self, statement, params=None):
                self.statements.append((str(statement), params))

        conn = FakeConn()
        _ensure_noches_schema_on_connection(conn)

        sql = "\n".join(statement for statement, _ in conn.statements)
        params = [params for _, params in conn.statements if params]
        self.assertIn("CREATE TABLE IF NOT EXISTS cobros_noches", sql)
        self.assertIn("estado ENUM('PAGADO', 'ANULADO')", sql)
        self.assertIn("estado_operativo ENUM('PENDIENTE', 'RETIRADO', 'CONVERTIDO')", sql)
        self.assertIn("idx_cobros_noches_estado_operativo", sql)
        self.assertIn("idx_cobros_noches_pendiente_cierre", sql)
        self.assertEqual(
            {item["clave"] for item in params},
            {"noches_activo", "noches_hora_inicio", "noches_hora_fin", "noches_valor"},
        )


if __name__ == "__main__":
    unittest.main()
