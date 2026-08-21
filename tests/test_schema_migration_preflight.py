import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from app.db.schema_migration_preflight import (
    collect_dry_run_preflight,
    evaluate_schema_migration_preflight,
    main,
)
from app.db.schema_migration_runner import plan_schema_migrations


class FakeEngine:
    pass


class SchemaMigrationPreflightTests(unittest.TestCase):
    def test_missing_database_blocks(self):
        result = evaluate_schema_migration_preflight(_inventory([], database=None), _plan([], database=None))

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(_check_status(result, "database_name"), "BLOCKED")

    def test_pending_migration_without_backup_blocks_future_apply(self):
        result = evaluate_schema_migration_preflight(_inventory([]), _plan([]))

        self.assertEqual(result["pending_migrations"], {"count": 1, "ids": ["001_create_schema_migrations"]})
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(_check_status(result, "backup_confirmed_for_future_apply"), "BLOCKED")
        self.assertFalse(result["apply"]["available"])

    def test_backup_confirmation_never_implies_execution(self):
        result = evaluate_schema_migration_preflight(
            _inventory([]), _plan([]), {"backup_confirmed": True, "environment": "staging"}
        )

        self.assertEqual(result["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertFalse(result["apply"]["available"])
        self.assertFalse(result["apply"]["will_execute"])
        self.assertEqual(result["apply"]["destructive_actions"], [])

    def test_no_pending_migrations_is_ok_for_current_dry_run_state(self):
        result = evaluate_schema_migration_preflight(_inventory(["schema_migrations"]), _plan(["schema_migrations"]))

        self.assertEqual(result["status"], "PREFLIGHT_OK")
        self.assertEqual(result["pending_migrations"], {"count": 0, "ids": []})
        self.assertEqual(result["future_apply_checklist"], [
            "Verify a current database backup.",
            "Test restoring the backup.",
            "Complete a staging migration run.",
            "Confirm the database is not production unless explicitly approved.",
        ])

    def test_cli_refuses_without_dry_run(self):
        error = io.StringIO()

        with redirect_stderr(error):
            with self.assertRaisesRegex(SystemExit, "2"):
                main([])

        self.assertIn("refusing to run without --dry-run", error.getvalue())

    def test_cli_dry_run_composes_inventory_plan_and_prints_deterministic_json(self):
        inventory = _inventory([])
        expected = evaluate_schema_migration_preflight(inventory, plan_schema_migrations(inventory), {"backup_confirmed": True, "environment": None})
        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=FakeEngine())

        with patch.dict(sys.modules, {"app.db.database": fake_database}):
            with patch(
                "app.db.schema_migration_preflight.collect_read_only_schema_inventory_from_engine",
                return_value=inventory,
            ) as collect_inventory:
                with redirect_stdout(output):
                    self.assertEqual(main(["--dry-run", "--backup-confirmed"]), 0)

        self.assertEqual(output.getvalue(), json.dumps(expected, indent=2, sort_keys=True) + "\n")
        collect_inventory.assert_called_once_with(fake_database.engine)

    def test_collection_uses_existing_inventory_path(self):
        inventory = _inventory([])

        with patch(
            "app.db.schema_migration_preflight.collect_read_only_schema_inventory_from_engine",
            return_value=inventory,
        ) as collect_inventory:
            result = collect_dry_run_preflight(FakeEngine())

        self.assertEqual(result["status"], "BLOCKED")
        collect_inventory.assert_called_once()


def _inventory(tables, database="parking"):
    return {
        "inventory_version": 1,
        "database": database,
        "tables": [{"table_name": table} for table in tables],
    }


def _plan(tables, database="parking"):
    return plan_schema_migrations(_inventory(tables, database))


def _check_status(result, name):
    return next(check["status"] for check in result["checks"] if check["name"] == name)


if __name__ == "__main__":
    unittest.main()
