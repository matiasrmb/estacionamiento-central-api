import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from app.db.schema_migration_runner import (
    MIGRATIONS,
    collect_dry_run_plan,
    main,
    plan_schema_migrations,
)


class FakeEngine:
    def __init__(self, connection=None):
        self.connection = connection

    def connect(self):
        if self.connection is not None:
            return self.connection
        raise AssertionError("This test patches inventory collection before an engine connection is needed")


class FakeResult:
    def __init__(self, *, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def scalar(self):
        return self.scalar_value

    def mappings(self):
        return self

    def all(self):
        return self.rows


class InventoryConnection:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if "DATABASE()" in sql:
            return FakeResult(scalar_value="parking")
        if "information_schema" in sql:
            return FakeResult()
        raise AssertionError(f"Unexpected query: {sql}")


class SchemaMigrationRunnerTests(unittest.TestCase):
    def test_refuses_without_dry_run(self):
        error = io.StringIO()

        with redirect_stderr(error):
            with self.assertRaisesRegex(SystemExit, "2"):
                main([])

        self.assertIn("refusing to run without --dry-run", error.getvalue())
        self.assertIn("apply mode is not implemented", error.getvalue())

    def test_plans_schema_migrations_creation_when_absent_without_executing_sql(self):
        plan = plan_schema_migrations(_inventory([]))

        migration = plan["migrations"][0]
        self.assertEqual(plan["schema_migrations"], {"present": False})
        self.assertEqual(migration["id"], "001_create_schema_migrations")
        self.assertEqual(migration["status"], "pending")
        self.assertEqual(migration["sql"], list(MIGRATIONS[0].statements))
        self.assertFalse(migration["will_execute"])

    def test_marks_schema_migrations_applied_when_present(self):
        plan = plan_schema_migrations(_inventory(["SCHEMA_MIGRATIONS"]))

        migration = plan["migrations"][0]
        self.assertEqual(plan["schema_migrations"], {"present": True})
        self.assertEqual(migration["status"], "applied")
        self.assertEqual(migration["sql"], [])
        self.assertFalse(migration["will_execute"])

    def test_plan_json_is_deterministic(self):
        ordered = _inventory(["configuracion", "schema_migrations"])
        unordered = _inventory(["SCHEMA_MIGRATIONS", "CONFIGURACION"])

        ordered_json = json.dumps(plan_schema_migrations(ordered), sort_keys=True)
        unordered_json = json.dumps(plan_schema_migrations(unordered), sort_keys=True)

        self.assertEqual(unordered_json, ordered_json)

    def test_marks_migration_unknown_when_tables_are_missing_from_inventory(self):
        plan = plan_schema_migrations({"inventory_version": 1, "database": "parking"})

        self.assertEqual(plan["schema_migrations"], {"present": None})
        self.assertEqual(plan["migrations"][0]["status"], "unknown")
        self.assertIn("migration status is unknown", plan["warnings"][-1])

    def test_collect_dry_run_plan_uses_inventory_result_without_mutating_engine(self):
        output = io.StringIO()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory([]),
        ) as collect_inventory:
            with redirect_stdout(output):
                plan = collect_dry_run_plan(FakeEngine())

        self.assertEqual(plan["migrations"][0]["status"], "pending")
        collect_inventory.assert_called_once()
        self.assertEqual(output.getvalue(), "")

    def test_dry_run_only_executes_inventory_selects_not_planned_ddl(self):
        connection = InventoryConnection()

        plan = collect_dry_run_plan(FakeEngine(connection))

        self.assertEqual(plan["migrations"][0]["status"], "pending")
        self.assertTrue(connection.statements)
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in connection.statements))
        self.assertNotIn(MIGRATIONS[0].statements[0], connection.statements)

    def test_cli_prints_deterministic_json_for_dry_run(self):
        expected_plan = plan_schema_migrations(_inventory([]))
        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=FakeEngine())

        with patch.dict(sys.modules, {"app.db.database": fake_database}):
            with patch(
                "app.db.schema_migration_runner.collect_dry_run_plan",
                return_value=expected_plan,
            ) as collect_plan:
                with redirect_stdout(output):
                    self.assertEqual(main(["--dry-run"]), 0)

        self.assertEqual(output.getvalue(), json.dumps(expected_plan, indent=2, sort_keys=True) + "\n")
        collect_plan.assert_called_once_with(fake_database.engine)


def _inventory(tables):
    return {
        "inventory_version": 1,
        "database": "parking",
        "tables": [{"table_name": table} for table in tables],
    }


if __name__ == "__main__":
    unittest.main()
