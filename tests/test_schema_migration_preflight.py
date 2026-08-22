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
        result = evaluate_schema_migration_preflight(
            _inventory(["schema_migrations"], migration_ids=["001_create_schema_migrations"]),
            _plan(["schema_migrations"], migration_ids=["001_create_schema_migrations"]),
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["pending_migrations"], {"count": 1, "ids": ["002_create_tipos_lavado"]})
        self.assertEqual(result["future_apply_checklist"], [
            "Verify a current database backup.",
            "Test restoring the backup.",
            "Complete a staging migration run.",
            "Confirm the database is not production unless explicitly approved.",
        ])

    def test_invalid_schema_migrations_contract_blocks_preflight(self):
        inventory = _inventory(["schema_migrations"], migration_id_column=False)
        result = evaluate_schema_migration_preflight(inventory, plan_schema_migrations(inventory))

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["invalid_contract_migrations"], ["001_create_schema_migrations"])
        self.assertEqual(_check_status(result, "schema_migrations_contract"), "BLOCKED")

    def test_reports_blocked_inconsistent_and_invalid_migrations(self):
        inventory = _inventory(["schema_migrations"], migration_ids=["001_create_schema_migrations"])
        plan = {
            "database": "parking",
            "schema_migrations": {"present": True},
            "migrations": [
                {"id": "003_widen_pagos_mensuales_metodo_pago", "status": "blocked_prerequisite"},
                {"id": "other", "status": "inconsistent_state"},
                {"id": "another", "status": "invalid_contract"},
            ],
        }

        result = evaluate_schema_migration_preflight(inventory, plan)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocked_migrations"], ["003_widen_pagos_mensuales_metodo_pago"])
        self.assertEqual(result["inconsistent_state_migrations"], ["other"])
        self.assertEqual(result["invalid_contract_migrations"], ["another"])
        self.assertEqual(_check_status(result, "migration_state_consistency"), "BLOCKED")

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


def _inventory(tables, database="parking", migration_ids=None, migration_id_column=True):
    inventory = {
        "inventory_version": 1,
        "database": database,
        "tables": [{"table_name": table} for table in tables],
    }
    if any(table.casefold() == "schema_migrations" for table in tables):
        inventory["columns"] = [
            {"table_name": "schema_migrations", "column_name": "migration_id", "column_type": "varchar(255)", "column_key": "PRI", "is_nullable": "NO"},
            {"table_name": "schema_migrations", "column_name": "applied_at", "column_type": "datetime", "column_default": "CURRENT_TIMESTAMP", "is_nullable": "NO"},
        ]
        if not migration_id_column:
            inventory["columns"] = inventory["columns"][1:]
        inventory["indexes"] = [{"table_name": "schema_migrations", "index_name": "PRIMARY", "column_name": "migration_id", "seq_in_index": 1}]
        inventory["migration_snapshot"] = {
            "source_table": "schema_migrations",
            "available": True,
            "records": [{"migration_id": migration_id} for migration_id in migration_ids or []],
        }
    return inventory


def _plan(tables, database="parking", migration_ids=None):
    return plan_schema_migrations(_inventory(tables, database, migration_ids))


def _check_status(result, name):
    return next(check["status"] for check in result["checks"] if check["name"] == name)


if __name__ == "__main__":
    unittest.main()
