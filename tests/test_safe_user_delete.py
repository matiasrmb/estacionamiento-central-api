import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch


def _install_optional_dependency_stubs():
    if "jose" not in sys.modules:
        jose_stub = types.ModuleType("jose")

        class JWTError(Exception):
            pass

        jose_stub.JWTError = JWTError
        sys.modules["jose"] = jose_stub

    if "app.core.security" not in sys.modules:
        security_stub = types.ModuleType("app.core.security")
        security_stub.decode_token = lambda token: {"sub": "admin", "rol": "admin"}

        class PasswordContextStub:
            def hash(self, value):
                return f"hashed-{value}"

        security_stub.pwd_context = PasswordContextStub()
        sys.modules["app.core.security"] = security_stub


_install_optional_dependency_stubs()

from fastapi import HTTPException

from app.api.v1.endpoints import usuarios
from app.repositories import users_repo


class FakeResult:
    def __init__(self, first_value=None, scalar_value=None, rowcount=1):
        self.first_value = first_value
        self.scalar_value = scalar_value
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.first_value

    def scalar(self):
        return self.scalar_value


class FakeConn:
    def __init__(self, user_row, activity_by_table=None, active_admins_after_delete=1, missing_tables=None):
        self.user_row = user_row
        self.activity_by_table = activity_by_table or {}
        self.active_admins_after_delete = active_admins_after_delete
        self.missing_tables = set(missing_tables or [])
        self.executed = []
        self.commits = 0

    def execute(self, query, params=None):
        query_text = str(query)
        self.executed.append((query_text, params or {}))
        for table in self.missing_tables:
            if f"FROM {table}" in query_text:
                raise RuntimeError(f"Table 'estacionamiento.{table}' doesn't exist")
        if "FROM usuarios" in query_text and "rol" in query_text:
            return FakeResult(first_value=self.user_row)
        if "COUNT(*)" in query_text and "FROM usuarios" in query_text:
            return FakeResult(scalar_value=self.active_admins_after_delete)
        for table, has_activity in self.activity_by_table.items():
            if f"FROM {table}" in query_text and has_activity:
                return FakeResult(first_value={"found": 1})
        return FakeResult(first_value=None, rowcount=1)

    def commit(self):
        self.commits += 1


@contextmanager
def fake_db_conn(conn):
    yield conn


class SafeUserDeleteTests(unittest.TestCase):
    @patch.object(users_repo, "db_conn")
    def test_hard_deletes_user_without_activity(self, db_conn):
        conn = FakeConn({"usuario": "nuevo", "rol": "operador", "activo": 1})
        db_conn.return_value = fake_db_conn(conn)

        result = users_repo.delete_user_safely("nuevo", current_usuario="admin")

        self.assertEqual(result, {"ok": True, "action": "deleted", "message": "USER_DELETED"})
        self.assertIn("DELETE FROM usuarios", "\n".join(query for query, _ in conn.executed))
        self.assertEqual(conn.commits, 1)

    @patch.object(users_repo, "db_conn")
    def test_hard_deletes_user_without_activity_when_optional_tables_are_missing(self, db_conn):
        conn = FakeConn(
            {"usuario": "nuevo", "rol": "operador", "activo": 1},
            missing_tables={"operaciones_servicio", "ingresos_eliminados", "print_jobs"},
        )
        db_conn.return_value = fake_db_conn(conn)

        result = users_repo.delete_user_safely("nuevo", current_usuario="admin")

        self.assertEqual(result, {"ok": True, "action": "deleted", "message": "USER_DELETED"})
        queries = "\n".join(query for query, _ in conn.executed)
        self.assertIn("FROM ingresos", queries)
        self.assertIn("DELETE FROM usuarios", queries)

    @patch.object(users_repo, "db_conn")
    def test_deactivates_user_with_activity_to_preserve_history(self, db_conn):
        conn = FakeConn(
            {"usuario": "operador", "rol": "operador", "activo": 1},
            activity_by_table={"ingresos": True},
        )
        db_conn.return_value = fake_db_conn(conn)

        result = users_repo.delete_user_safely("operador", current_usuario="admin")

        self.assertEqual(result["action"], "deactivated")
        self.assertEqual(result["message"], "USER_DEACTIVATED_HISTORY_PRESERVED")
        consultas = "\n".join(query for query, _ in conn.executed)
        self.assertIn("UPDATE usuarios SET activo", consultas)
        self.assertNotIn("DELETE FROM usuarios", consultas)

    @patch.object(users_repo, "db_conn")
    def test_blocks_current_user_delete(self, db_conn):
        conn = FakeConn({"usuario": "admin", "rol": "administrador", "activo": 1})
        db_conn.return_value = fake_db_conn(conn)

        with self.assertRaises(PermissionError) as ctx:
            users_repo.delete_user_safely("admin", current_usuario="admin")

        self.assertEqual(str(ctx.exception), "CANNOT_DELETE_CURRENT_USER")
        self.assertNotIn("DELETE FROM usuarios", "\n".join(query for query, _ in conn.executed))

    @patch.object(users_repo, "db_conn")
    def test_blocks_last_active_admin_delete(self, db_conn):
        conn = FakeConn(
            {"usuario": "admin2", "rol": "administrador", "activo": 1},
            active_admins_after_delete=0,
        )
        db_conn.return_value = fake_db_conn(conn)

        with self.assertRaises(PermissionError) as ctx:
            users_repo.delete_user_safely("admin2", current_usuario="admin")

        self.assertEqual(str(ctx.exception), "CANNOT_DELETE_LAST_ADMIN")

    @patch.object(usuarios, "repo_delete_user_safely")
    def test_endpoint_maps_current_user_block_to_403(self, repo_delete):
        repo_delete.side_effect = PermissionError("CANNOT_DELETE_CURRENT_USER")

        with self.assertRaises(HTTPException) as ctx:
            usuarios.eliminar_usuario("admin", _user={"sub": "admin"})

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "CANNOT_DELETE_CURRENT_USER")


if __name__ == "__main__":
    unittest.main()
