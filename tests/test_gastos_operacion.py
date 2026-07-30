import unittest
from datetime import datetime
from pathlib import Path
import re
from unittest.mock import patch

from pydantic import ValidationError

from app.api.v1.endpoints import gastos
from app.repositories import gastos_repo
from app.schemas.gastos import GastoCreateIn


class FakeDbConn:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return False


class FakeResult:
    def __init__(self, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar(self):
        return self.scalar_value


class FakeConnection:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.committed = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        if "LAST_INSERT_ID" in sql:
            return FakeResult(scalar_value=17)
        if "FROM gastos_operacion" in sql:
            return FakeResult(rows=self.rows)
        return FakeResult()

    def commit(self):
        self.committed = True


class GastosOperacionTests(unittest.TestCase):
    migrations_dir = Path(__file__).resolve().parents[1].joinpath("app", "db", "migrations")

    def test_migrations_do_not_use_unsupported_mysql_add_index_if_not_exists(self):
        unsupported_syntax = re.compile(r"ADD\s+INDEX\s+IF\s+NOT\s+EXISTS", re.IGNORECASE)

        for migration_path in self.migrations_dir.glob("*.sql"):
            with self.subTest(migration=migration_path.name):
                migration = migration_path.read_text(encoding="utf-8")
                self.assertNotRegex(migration, unsupported_syntax)

    def test_guarded_index_migrations_use_mysql_dynamic_index_creation(self):
        guarded_indexes = {
            "003_solo_lavado_accounting.sql": ["idx_operaciones_servicio_cierre"],
            "004_gastos_operacion.sql": [
                "idx_usos_bano_pendiente",
                "idx_usos_bano_cierre",
            ],
        }

        for migration_name, index_names in guarded_indexes.items():
            migration = self.migrations_dir.joinpath(migration_name).read_text(encoding="utf-8")

            with self.subTest(migration=migration_name):
                self.assertIn("information_schema.statistics", migration)
                self.assertIn("PREPARE stmt FROM @sql", migration)
                self.assertIn("EXECUTE stmt", migration)
                for index_name in index_names:
                    self.assertIn(f"index_name = '{index_name}'", migration)
                    self.assertIn(f"ADD INDEX {index_name}", migration)

    def test_schema_strips_text_and_rejects_blank_or_non_positive_amounts(self):
        payload = GastoCreateIn(categoria=" Insumos ", descripcion=" Agua ", monto=250)

        self.assertEqual(payload.categoria, "Insumos")
        self.assertEqual(payload.descripcion, "Agua")
        with self.assertRaises(ValidationError):
            GastoCreateIn(categoria="   ", descripcion="Agua", monto=250)
        with self.assertRaises(ValidationError):
            GastoCreateIn(categoria="Insumos", descripcion="Agua", monto=0)
        with self.assertRaises(ValidationError):
            GastoCreateIn(categoria="Insumos", descripcion="Agua", monto=250.0)

    def test_create_uses_server_timestamp_and_authenticated_user(self):
        conn = FakeConnection()
        with patch.object(gastos_repo, "ensure_gastos_operacion_schema"), \
             patch.object(gastos_repo, "db_conn", return_value=FakeDbConn(conn)), \
             patch.object(gastos_repo, "datetime") as now:
            now.now.return_value = datetime(2026, 7, 1, 10, 30)
            result = gastos_repo.crear_gasto("Insumos", "Agua", 250, "admin")

        insert_sql, params = conn.executed[0]
        self.assertIn("INSERT INTO gastos_operacion", insert_sql)
        self.assertEqual(params["fecha_hora"], datetime(2026, 7, 1, 10, 30))
        self.assertEqual(params["usuario"], "admin")
        self.assertEqual(result["id_gasto"], 17)
        self.assertEqual(result["id_cierre"], None)
        self.assertTrue(conn.committed)

    def test_pending_list_excludes_closed_expenses_and_sums_amounts(self):
        conn = FakeConnection(rows=[
            {
                "id_gasto": 1,
                "fecha_hora": datetime(2026, 7, 1, 9, 0),
                "categoria": "Insumos",
                "descripcion": "Agua",
                "monto": 250,
                "usuario": "admin",
                "id_cierre": None,
            },
        ])
        with patch.object(gastos_repo, "ensure_gastos_operacion_schema"), \
             patch.object(gastos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = gastos_repo.list_gastos_pendientes()

        self.assertIn("WHERE id_cierre IS NULL", conn.executed[0][0])
        self.assertEqual(result["total_gastos"], 250)
        self.assertEqual(result["items"][0]["fecha_hora"], "2026-07-01T09:00:00")

    def test_endpoint_passes_only_validated_payload_and_authenticated_user(self):
        payload = GastoCreateIn(categoria="Insumos", descripcion="Agua", monto=250)
        with patch.object(gastos, "crear_gasto", return_value={"id_gasto": 1}) as create:
            result = gastos.crear_gasto_endpoint(payload, user={"sub": "admin"})

        self.assertEqual(result, {"id_gasto": 1})
        create.assert_called_once_with("Insumos", "Agua", 250, "admin")


if __name__ == "__main__":
    unittest.main()
