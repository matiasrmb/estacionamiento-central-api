import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from app.db.schema_migration_runner import (
    MIGRATIONS,
    MIGRATION_001_RECORD_SQL,
    apply_001_create_schema_migrations,
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

    def begin(self):
        if self.connection is not None:
            return self.connection
        raise AssertionError("Apply requires a transaction connection")


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


class ApplyConnection:
    def __init__(self, *, fail_insert=False):
        self.statements = []
        self.fail_insert = fail_insert

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        if self.fail_insert and "INSERT INTO schema_migrations" in str(statement):
            raise RuntimeError("simulated insert failure")


class SchemaMigrationRunnerTests(unittest.TestCase):
    def test_refuses_without_dry_run(self):
        error = io.StringIO()

        with redirect_stderr(error):
            with self.assertRaisesRegex(SystemExit, "2"):
                main([])

        self.assertIn("refusing to run without --dry-run or --apply", error.getvalue())

    def test_plans_schema_migrations_creation_when_absent_without_executing_sql(self):
        plan = plan_schema_migrations(_inventory([]))

        migration = plan["migrations"][0]
        self.assertEqual(plan["schema_migrations"], {"present": False, "contract": {"valid": None, "issues": []}})
        self.assertEqual(migration["id"], "001_create_schema_migrations")
        self.assertEqual(migration["status"], "pending")
        self.assertEqual(migration["sql"], list(MIGRATIONS[0].statements))
        self.assertFalse(migration["will_execute"])

    def test_marks_schema_migrations_applied_when_present(self):
        plan = plan_schema_migrations(_inventory(["SCHEMA_MIGRATIONS"], migration_ids=["001_create_schema_migrations"]))

        migration = plan["migrations"][0]
        self.assertEqual(plan["schema_migrations"], {"present": True, "contract": {"valid": True, "issues": []}})
        self.assertEqual(migration["status"], "applied")
        self.assertEqual(migration["sql"], [])
        self.assertFalse(migration["will_execute"])

    def test_plan_json_is_deterministic(self):
        ordered = _inventory(["configuracion", "schema_migrations"], migration_ids=["001_create_schema_migrations"])
        unordered = _inventory(["SCHEMA_MIGRATIONS", "CONFIGURACION"], migration_ids=["001_create_schema_migrations"])

        ordered_json = json.dumps(plan_schema_migrations(ordered), sort_keys=True)
        unordered_json = json.dumps(plan_schema_migrations(unordered), sort_keys=True)

        self.assertEqual(unordered_json, ordered_json)

    def test_marks_migration_unknown_when_tables_are_missing_from_inventory(self):
        plan = plan_schema_migrations({"inventory_version": 1, "database": "parking"})

        self.assertEqual(plan["schema_migrations"], {"present": None, "contract": {"valid": None, "issues": []}})
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

    def test_apply_refuses_without_required_confirmations(self):
        connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory([]),
        ):
            result = apply_001_create_schema_migrations(
                FakeEngine(connection), backup_confirmed=False, dev_database_confirmed=False, expected_database="parking"
            )

        self.assertEqual(result["status"], "refused")
        self.assertEqual(connection.statements, [])

    def test_apply_refuses_without_expected_database(self):
        connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory([]),
        ):
            result = apply_001_create_schema_migrations(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True
            )

        self.assertEqual(result["status"], "refused")
        self.assertEqual(connection.statements, [])

    def test_apply_refuses_when_expected_database_does_not_match(self):
        connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory([], database="parking"),
        ):
            result = apply_001_create_schema_migrations(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="other"
            )

        self.assertEqual(result["status"], "refused")
        self.assertIn("does not match", result["warnings"][0])
        self.assertEqual(connection.statements, [])

    def test_apply_noops_when_migration_is_recorded(self):
        connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory(["schema_migrations"], migration_ids=["001_create_schema_migrations"]),
        ):
            result = apply_001_create_schema_migrations(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(result["status"], "noop")
        self.assertEqual(connection.statements, [])

    def test_apply_refuses_existing_table_missing_migration_id_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], migration_id_column=False))

    def test_apply_refuses_existing_table_with_non_primary_migration_id_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], migration_id_primary=False))

    def test_apply_refuses_existing_table_with_composite_primary_key_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], composite_primary_key=True))

    def test_apply_refuses_existing_table_with_nullable_migration_id_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], migration_id_nullable=True))

    def test_apply_refuses_existing_table_with_wrong_migration_id_type_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], migration_id_type="varchar(64)"))

    def test_apply_refuses_existing_table_missing_applied_at_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], applied_at_column=False))

    def test_apply_refuses_existing_table_with_invalid_applied_at_default_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], applied_at_default=None))

    def test_apply_refuses_existing_table_with_invalid_applied_at_type_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], applied_at_type="timestamp"))

    def test_apply_refuses_existing_table_with_nullable_applied_at_without_sql(self):
        self._assert_invalid_contract_refused(_inventory(["schema_migrations"], applied_at_nullable=True))

    def test_dry_run_warns_when_existing_tracking_table_contract_is_invalid(self):
        plan = plan_schema_migrations(_inventory(["schema_migrations"], applied_at_type="timestamp"))

        self.assertEqual(plan["migrations"][0]["status"], "invalid_contract")
        self.assertIn("invalid contract", plan["warnings"][-1])

    def _assert_invalid_contract_refused(self, inventory):
        connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=inventory,
        ):
            result = apply_001_create_schema_migrations(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(result["executed_statements_count"], 0)
        self.assertEqual(connection.statements, [])

    def test_apply_executes_only_create_then_migration_record(self):
        connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory([]),
        ):
            result = apply_001_create_schema_migrations(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["executed_statements_count"], 2)
        self.assertEqual(result["executed_statement_types"], ["CREATE TABLE", "INSERT"])
        self.assertEqual(connection.statements, [
            (MIGRATIONS[0].statements[0], None),
            (MIGRATION_001_RECORD_SQL, {"migration_id": "001_create_schema_migrations"}),
        ])

    def test_apply_repairs_existing_tracking_table_without_migration_record(self):
        connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory(["schema_migrations"], migration_ids=[]),
        ):
            result = apply_001_create_schema_migrations(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(result["status"], "repaired")
        self.assertEqual(connection.statements, [
            (MIGRATION_001_RECORD_SQL, {"migration_id": "001_create_schema_migrations"}),
        ])

    def test_insert_failure_after_create_is_clear_and_retry_repairs(self):
        failed_connection = ApplyConnection(fail_insert=True)
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory([]),
        ):
            failure = apply_001_create_schema_migrations(
                FakeEngine(failed_connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(failure["status"], "failed_after_create")
        self.assertEqual(failure["executed_statement_types"], ["CREATE TABLE"])
        self.assertIn("CREATE TABLE succeeded", failure["warnings"][0])
        retry_connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value=_inventory(["schema_migrations"], migration_ids=[]),
        ):
            retry = apply_001_create_schema_migrations(
                FakeEngine(retry_connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(retry["status"], "repaired")
        self.assertEqual(retry_connection.statements, [
            (MIGRATION_001_RECORD_SQL, {"migration_id": "001_create_schema_migrations"}),
        ])

    def test_apply_refuses_unknown_inventory(self):
        connection = ApplyConnection()
        with patch(
            "app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine",
            return_value={"inventory_version": 1, "database": "parking"},
        ):
            result = apply_001_create_schema_migrations(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(result["status"], "refused")
        self.assertEqual(connection.statements, [])

    def test_cli_apply_requires_expected_database_before_importing_database(self):
        error = io.StringIO()

        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(["--apply-001-create-schema-migrations"])

        self.assertIn("--expected-database is required for apply", error.getvalue())

    def test_cli_apply_requires_dev_database_confirmation_before_importing_database(self):
        error = io.StringIO()

        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(["--apply-001-create-schema-migrations", "--expected-database", "parking"])

        self.assertIn("--confirm-dev-db is required for apply", error.getvalue())

    def test_cli_apply_requires_backup_confirmation_before_importing_database(self):
        error = io.StringIO()

        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main([
                        "--apply-001-create-schema-migrations", "--expected-database", "parking", "--confirm-dev-db",
                    ])

        self.assertIn("--backup-confirmed is required for apply", error.getvalue())

    def test_cli_apply_returns_nonzero_for_refused_database_mismatch(self):
        self._assert_cli_apply_exit_code({"status": "refused"}, 1)

    def test_cli_apply_returns_nonzero_for_failed_after_create(self):
        self._assert_cli_apply_exit_code({"status": "failed_after_create"}, 1)

    def test_cli_apply_returns_nonzero_for_invalid_contract(self):
        self._assert_cli_apply_exit_code({"status": "invalid_contract"}, 1)

    def test_cli_apply_returns_nonzero_for_other_unsuccessful_outcomes(self):
        for status in ("failed", "unknown", "unexpected"):
            with self.subTest(status=status):
                self._assert_cli_apply_exit_code({"status": status}, 1)

    def test_cli_apply_returns_zero_for_successful_outcomes(self):
        for status in ("applied", "noop", "repaired"):
            with self.subTest(status=status):
                self._assert_cli_apply_exit_code({"status": status}, 0)

    def _assert_cli_apply_exit_code(self, result, expected_exit_code):
        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=FakeEngine())
        with patch.dict(sys.modules, {"app.db.database": fake_database}):
            with patch(
                "app.db.schema_migration_runner.apply_001_create_schema_migrations",
                return_value=result,
            ) as apply:
                with redirect_stdout(output):
                    self.assertEqual(main([
                        "--apply-001-create-schema-migrations", "--backup-confirmed", "--confirm-dev-db",
                        "--expected-database", "parking",
                    ]), expected_exit_code)

        self.assertEqual(json.loads(output.getvalue()), result)
        apply.assert_called_once_with(
            fake_database.engine, backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
        )


def _inventory(
    tables, database="parking", migration_ids=None, migration_id_column=True,
    migration_id_primary=True, migration_id_type="varchar(255)", applied_at_column=True,
    applied_at_type="datetime", applied_at_default="CURRENT_TIMESTAMP",
    composite_primary_key=False, migration_id_nullable=False, applied_at_nullable=False,
):
    inventory = {
        "inventory_version": 1,
        "database": database,
        "tables": [{"table_name": table} for table in tables],
    }
    if any(table.casefold() == "schema_migrations" for table in tables):
        columns = []
        if migration_id_column:
            columns.append({
                "table_name": "schema_migrations", "column_name": "migration_id",
                "column_type": migration_id_type, "column_key": "PRI" if migration_id_primary else "",
                "is_nullable": "YES" if migration_id_nullable else "NO",
            })
        if composite_primary_key:
            columns.append({
                "table_name": "schema_migrations", "column_name": "scope",
                "column_type": "varchar(255)", "column_key": "PRI", "is_nullable": "NO",
            })
        if applied_at_column:
            columns.append({
                "table_name": "schema_migrations", "column_name": "applied_at",
                "column_type": applied_at_type, "column_default": applied_at_default,
                "is_nullable": "YES" if applied_at_nullable else "NO",
            })
        inventory["columns"] = columns
        inventory["indexes"] = [{
            "table_name": "schema_migrations", "index_name": "PRIMARY",
            "column_name": "migration_id", "seq_in_index": 1,
        }] if migration_id_primary else []
        if composite_primary_key:
            inventory["indexes"].append({
                "table_name": "schema_migrations", "index_name": "PRIMARY",
                "column_name": "scope", "seq_in_index": 2,
            })
        inventory["migration_snapshot"] = {
            "source_table": "schema_migrations",
            "available": True,
            "records": [{"migration_id": migration_id, "applied_at": "2026-01-01T00:00:00"} for migration_id in migration_ids or []],
        }
    return inventory


if __name__ == "__main__":
    unittest.main()
