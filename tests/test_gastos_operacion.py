import unittest
from datetime import datetime
from pathlib import Path
import re
from unittest.mock import patch

from pydantic import ValidationError

from app.api.v1.endpoints import gastos
from app.repositories import gastos_repo
from app.schemas.gastos import GastoCreateIn, GastoDeleteIn, GastoUpdateIn


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

    def first(self):
        return self.rows[0] if self.rows else None

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


class MissingAuditConnection(FakeConnection):
    def execute(self, statement, params=None):
        sql = str(statement)
        if "gastos_operacion_auditoria" in sql:
            self.executed.append((sql, params))
            raise RuntimeError("audit table missing")
        return super().execute(statement, params)


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
        payload = GastoCreateIn(categoria=" Insumos ", descripcion=" Agua ", monto=250, confirmado=True)

        self.assertEqual(payload.categoria, "Insumos")
        self.assertEqual(payload.descripcion, "Agua")
        with self.assertRaises(ValidationError):
            GastoCreateIn(categoria="   ", descripcion="Agua", monto=250, confirmado=True)
        with self.assertRaises(ValidationError):
            GastoCreateIn(categoria="Insumos", descripcion="Agua", monto=0, confirmado=True)
        with self.assertRaises(ValidationError):
            GastoCreateIn(categoria="Insumos", descripcion="Agua", monto=250.0, confirmado=True)
        with self.assertRaises(ValidationError):
            GastoCreateIn(categoria="Insumos", descripcion="Agua", monto=250)

    def test_update_and_delete_schemas_require_confirmation(self):
        update = GastoUpdateIn(categoria=" Insumos ", descripcion=" Agua ", monto=250, confirmado=True)

        self.assertEqual(update.categoria, "Insumos")
        self.assertEqual(update.descripcion, "Agua")
        with self.assertRaises(ValidationError):
            GastoUpdateIn(categoria="Insumos", descripcion="Agua", monto=250)
        with self.assertRaises(ValidationError):
            GastoDeleteIn()

    def test_create_uses_server_timestamp_and_authenticated_user(self):
        conn = FakeConnection()
        with patch.object(gastos_repo, "db_conn", return_value=FakeDbConn(conn)), \
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
        self.assertFalse(any(keyword in sql.upper() for sql, _ in conn.executed for keyword in ("CREATE TABLE", "ALTER TABLE", "CREATE INDEX")))

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
        with patch.object(gastos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = gastos_repo.list_gastos_pendientes()

        self.assertIn("WHERE id_cierre IS NULL", conn.executed[0][0])
        self.assertFalse(any(keyword in sql.upper() for sql, _ in conn.executed for keyword in ("CREATE TABLE", "ALTER TABLE", "CREATE INDEX")))
        self.assertEqual(result["total_gastos"], 250)
        self.assertEqual(result["items"][0]["fecha_hora"], "2026-07-01T09:00:00")

    def test_endpoint_passes_only_validated_payload_and_authenticated_user(self):
        payload = GastoCreateIn(categoria="Insumos", descripcion="Agua", monto=250, confirmado=True)
        with patch.object(gastos, "crear_gasto", return_value={"id_gasto": 1}) as create:
            result = gastos.crear_gasto_endpoint(payload, user={"sub": "admin"})

        self.assertEqual(result, {"id_gasto": 1})
        create.assert_called_once_with("Insumos", "Agua", 250, "admin")

    def test_endpoint_rejects_create_without_confirmation(self):
        payload = GastoCreateIn(categoria="Insumos", descripcion="Agua", monto=250, confirmado=False)

        with self.assertRaises(gastos.HTTPException) as raised:
            gastos.crear_gasto_endpoint(payload, user={"sub": "admin"})

        self.assertEqual(raised.exception.status_code, 400)

    def test_admin_update_and_delete_endpoints_call_repository(self):
        update_payload = GastoUpdateIn(categoria="Insumos", descripcion="Agua", monto=300, confirmado=True)
        delete_payload = GastoDeleteIn(confirmado=True)

        with patch.object(gastos, "editar_gasto", return_value={"id_gasto": 7}) as update:
            self.assertEqual(gastos.editar_gasto_endpoint(7, update_payload, user={"sub": "admin"}), {"id_gasto": 7})
        with patch.object(gastos, "eliminar_gasto", return_value={"ok": True, "id_gasto": 7}) as delete:
            self.assertEqual(gastos.eliminar_gasto_endpoint(7, delete_payload, user={"sub": "admin"}), {"ok": True, "id_gasto": 7})

        update.assert_called_once_with(7, "Insumos", "Agua", 300, "admin")
        delete.assert_called_once_with(7, "admin")

    def test_endpoint_maps_missing_audit_table_to_service_unavailable(self):
        payload = GastoUpdateIn(categoria="Insumos", descripcion="Agua", monto=300, confirmado=True)

        with patch.object(gastos, "editar_gasto", side_effect=gastos_repo.GastoAuditUnavailableError()):
            with self.assertRaises(gastos.HTTPException) as raised:
                gastos.editar_gasto_endpoint(7, payload, user={"sub": "admin"})

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "GASTOS_AUDIT_MIGRATION_REQUIRED")

    def test_repository_updates_pending_expense_and_inserts_audit_snapshot(self):
        conn = FakeConnection(rows=[{
            "id_gasto": 7,
            "fecha_hora": datetime(2026, 7, 1, 9, 0),
            "categoria": "Insumos",
            "descripcion": "Agua",
            "monto": 250,
            "usuario": "operador",
            "id_cierre": None,
        }])
        with patch.object(gastos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = gastos_repo.editar_gasto(7, "Servicios", "Luz", 500, "admin")

        sql = "\n".join(query for query, _ in conn.executed)
        self.assertIn("FOR UPDATE", sql)
        self.assertIn("UPDATE gastos_operacion", sql)
        self.assertIn("INSERT INTO gastos_operacion_auditoria", sql)
        audit_params = conn.executed[-1][1]
        self.assertEqual(audit_params["accion"], "EDITAR")
        self.assertIn('"categoria": "Insumos"', audit_params["snapshot_anterior"])
        self.assertIn('"categoria": "Servicios"', audit_params["snapshot_nuevo"])
        self.assertEqual(result["monto"], 500)
        self.assertTrue(conn.committed)

    def test_repository_deletes_pending_expense_and_inserts_audit_snapshot(self):
        conn = FakeConnection(rows=[{
            "id_gasto": 7,
            "fecha_hora": datetime(2026, 7, 1, 9, 0),
            "categoria": "Insumos",
            "descripcion": "Agua",
            "monto": 250,
            "usuario": "operador",
            "id_cierre": None,
        }])
        with patch.object(gastos_repo, "db_conn", return_value=FakeDbConn(conn)):
            result = gastos_repo.eliminar_gasto(7, "admin")

        sql = "\n".join(query for query, _ in conn.executed)
        self.assertIn("DELETE FROM gastos_operacion", sql)
        audit_params = conn.executed[-1][1]
        self.assertEqual(audit_params["accion"], "ELIMINAR")
        self.assertIn('"id_gasto": 7', audit_params["snapshot_anterior"])
        self.assertIsNone(audit_params["snapshot_nuevo"])
        self.assertEqual(result, {"ok": True, "id_gasto": 7})

    def test_repository_rejects_closed_expense_updates_and_deletes(self):
        row = {
            "id_gasto": 7,
            "fecha_hora": datetime(2026, 7, 1, 9, 0),
            "categoria": "Insumos",
            "descripcion": "Agua",
            "monto": 250,
            "usuario": "operador",
            "id_cierre": 3,
        }
        for operation in (
            lambda conn: gastos_repo.editar_gasto(7, "Servicios", "Luz", 500, "admin"),
            lambda conn: gastos_repo.eliminar_gasto(7, "admin"),
        ):
            conn = FakeConnection(rows=[row])
            with self.subTest(operation=operation), patch.object(gastos_repo, "db_conn", return_value=FakeDbConn(conn)):
                with self.assertRaises(gastos_repo.GastoCerradoError):
                    operation(conn)
                self.assertFalse(conn.committed)

    def test_repository_rejects_mutation_when_audit_table_is_missing_before_update(self):
        conn = MissingAuditConnection(rows=[{
            "id_gasto": 7,
            "fecha_hora": datetime(2026, 7, 1, 9, 0),
            "categoria": "Insumos",
            "descripcion": "Agua",
            "monto": 250,
            "usuario": "operador",
            "id_cierre": None,
        }])

        with patch.object(gastos_repo, "db_conn", return_value=FakeDbConn(conn)):
            with self.assertRaises(gastos_repo.GastoAuditUnavailableError):
                gastos_repo.editar_gasto(7, "Servicios", "Luz", 500, "admin")

        sql = "\n".join(query for query, _ in conn.executed)
        self.assertIn("gastos_operacion_auditoria", sql)
        self.assertNotIn("UPDATE gastos_operacion", sql)
        self.assertFalse(conn.committed)


if __name__ == "__main__":
    unittest.main()
