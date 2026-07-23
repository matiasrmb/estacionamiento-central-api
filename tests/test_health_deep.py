from contextlib import contextmanager
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.v1.endpoints import health


class FakeConnection:
    def __init__(self, tables=None, columns=None, fail=False):
        self.tables = tables if tables is not None else health.REQUIRED_TABLES
        self.columns = columns if columns is not None else health.REQUIRED_PRINT_JOB_COLUMNS
        self.fail = fail

    def execute(self, statement, params=None):
        if self.fail:
            raise RuntimeError("db unavailable with secret details")

        sql = str(statement)
        if "SELECT 1" in sql:
            return [(1,)]
        if "information_schema.tables" in sql:
            requested = set(params["tables"])
            return [(name,) for name in sorted(self.tables & requested)]
        if "information_schema.columns" in sql:
            requested = set(params["columns"])
            return [(name,) for name in sorted(self.columns & requested)]
        raise AssertionError(f"Unexpected query: {sql}")


@contextmanager
def fake_db_conn(conn):
    yield conn


class DeepHealthTests(unittest.TestCase):
    @patch.object(health, "db_conn")
    def test_deep_health_returns_ok_when_db_and_schema_are_valid(self, db_conn):
        db_conn.return_value = fake_db_conn(FakeConnection())

        result = health.deep_health()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["checks"]["db_connection"]["status"], "ok")
        self.assertEqual(result["checks"]["required_tables"], {"status": "ok", "missing": []})
        self.assertEqual(result["checks"]["print_jobs_columns"], {"status": "ok", "missing": []})

    @patch.object(health, "db_conn")
    def test_deep_health_raises_503_when_required_table_is_missing(self, db_conn):
        tables = health.REQUIRED_TABLES - {"print_jobs"}
        db_conn.return_value = fake_db_conn(FakeConnection(tables=tables))

        with self.assertRaises(HTTPException) as raised:
            health.deep_health()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["status"], "fail")
        self.assertEqual(raised.exception.detail["checks"]["required_tables"]["missing"], ["print_jobs"])

    @patch.object(health, "db_conn")
    def test_deep_health_raises_503_when_print_jobs_column_is_missing(self, db_conn):
        columns = health.REQUIRED_PRINT_JOB_COLUMNS - {"locked_by"}
        db_conn.return_value = fake_db_conn(FakeConnection(columns=columns))

        with self.assertRaises(HTTPException) as raised:
            health.deep_health()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["status"], "fail")
        self.assertEqual(raised.exception.detail["checks"]["print_jobs_columns"]["missing"], ["locked_by"])

    @patch.object(health, "db_conn")
    def test_deep_health_raises_503_without_exposing_db_error(self, db_conn):
        db_conn.return_value = fake_db_conn(FakeConnection(fail=True))

        with self.assertRaises(HTTPException) as raised:
            health.deep_health()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["status"], "fail")
        self.assertEqual(
            raised.exception.detail["checks"]["db_connection"],
            {"status": "fail", "error": "database check failed"},
        )
        self.assertNotIn("secret", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
