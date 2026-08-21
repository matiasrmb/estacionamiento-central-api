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
    MIGRATION_002_SEED_SQL,
    apply_001_create_schema_migrations,
    apply_002_create_tipos_lavado,
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
    def __init__(self, *, fail_insert=False, fail_seed=False):
        self.statements = []
        self.fail_insert = fail_insert
        self.fail_seed = fail_seed

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        if self.fail_insert and "INSERT INTO schema_migrations" in str(statement):
            raise RuntimeError("simulated insert failure")
        if self.fail_seed and "INSERT INTO tipos_lavado" in str(statement):
            raise RuntimeError("simulated seed failure")


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

    def test_002_is_pending_when_001_is_recorded_and_table_is_absent(self):
        plan = plan_schema_migrations(_inventory(["schema_migrations"], migration_ids=["001_create_schema_migrations"]))

        self.assertEqual(plan["migrations"][1]["status"], "pending")
        self.assertEqual(plan["migrations"][1]["sql"], [MIGRATIONS[1].statements[0], MIGRATION_002_SEED_SQL, MIGRATION_001_RECORD_SQL])

    def test_002_create_table_sql_matches_required_contract(self):
        expected_sql = (
            "CREATE TABLE IF NOT EXISTS tipos_lavado (\n"
            "    id_tipo_lavado INT AUTO_INCREMENT PRIMARY KEY,\n"
            "    codigo VARCHAR(50) NOT NULL UNIQUE,\n"
            "    nombre VARCHAR(80) NOT NULL,\n"
            "    activo TINYINT(1) NOT NULL DEFAULT 1,\n"
            "    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,\n"
            "    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP\n"
            ")"
        )

        self.assertEqual(MIGRATIONS[1].statements, (expected_sql,))

    def test_002_seed_sql_preserves_existing_mutable_values(self):
        expected_sql = (
            "INSERT INTO tipos_lavado (codigo, nombre, activo) "
            "VALUES ('lavado_general', 'Lavado', 1) "
            "ON DUPLICATE KEY UPDATE codigo = codigo"
        )

        self.assertEqual(MIGRATION_002_SEED_SQL, expected_sql)
        self.assertNotIn("nombre =", MIGRATION_002_SEED_SQL)
        self.assertNotIn("activo =", MIGRATION_002_SEED_SQL)
        self.assertNotIn("created_at =", MIGRATION_002_SEED_SQL)
        self.assertNotIn("updated_at =", MIGRATION_002_SEED_SQL)

    def test_002_is_blocked_when_001_is_missing(self):
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=_inventory(["schema_migrations"], migration_ids=[])):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["status"], "refused")
        self.assertEqual(connection.statements, [])

    def test_002_creates_seeds_and_records_when_table_is_absent(self):
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=_inventory(["schema_migrations"], migration_ids=["001_create_schema_migrations"])):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["status"], "applied")
        self.assertEqual(connection.statements, [
            (MIGRATIONS[1].statements[0], None),
            (MIGRATION_002_SEED_SQL, None),
            (MIGRATION_001_RECORD_SQL, {"migration_id": "002_create_tipos_lavado"}),
        ])

    def test_002_valid_table_without_seed_executes_seed_and_record_only(self):
        connection = ApplyConnection()
        inventory = _inventory(["schema_migrations", "tipos_lavado"], migration_ids=["001_create_schema_migrations"], tipos_lavado_seed=False)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["executed_statement_types"], ["INSERT seed", "INSERT migration record"])
        self.assertEqual([statement for statement, _ in connection.statements], [MIGRATION_002_SEED_SQL, MIGRATION_001_RECORD_SQL])

    def test_002_preserves_modified_or_inactive_seed_and_only_records(self):
        connection = ApplyConnection()
        inventory = _inventory(["schema_migrations", "tipos_lavado"], migration_ids=["001_create_schema_migrations"], tipos_lavado_seed=True)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["status"], "repaired")
        self.assertEqual(connection.statements, [(MIGRATION_001_RECORD_SQL, {"migration_id": "002_create_tipos_lavado"})])

    def test_002_invalid_contract_refuses_without_sql(self):
        connection = ApplyConnection()
        inventory = _inventory(["schema_migrations", "tipos_lavado"], migration_ids=["001_create_schema_migrations"], tipos_lavado_valid=False)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(connection.statements, [])

    def test_002_composite_codigo_unique_contract_refuses_without_sql(self):
        connection = ApplyConnection()
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado"],
            migration_ids=["001_create_schema_migrations"],
            tipos_lavado_composite_codigo_unique=True,
        )
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(result["executed_statements_count"], 0)
        self.assertEqual(connection.statements, [])

    def test_002_recorded_with_valid_table_is_noop_without_sql(self):
        connection = ApplyConnection()
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
        )
        plan = plan_schema_migrations(inventory)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(plan["migrations"][1]["status"], "applied")
        self.assertEqual(result["status"], "noop")
        self.assertEqual(connection.statements, [])

    def test_002_recorded_with_composite_codigo_unique_is_invalid_without_sql(self):
        connection = ApplyConnection()
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
            tipos_lavado_composite_codigo_unique=True,
        )

        plan = plan_schema_migrations(inventory)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(plan["migrations"][1]["status"], "invalid_contract")
        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(result["executed_statements_count"], 0)
        self.assertEqual(connection.statements, [])

    def test_002_recorded_without_table_is_inconsistent_and_refused_without_sql(self):
        connection = ApplyConnection()
        inventory = _inventory(
            ["schema_migrations"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
        )

        plan = plan_schema_migrations(inventory)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_002_create_tipos_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(plan["migrations"][1]["status"], "inconsistent_state")
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["executed_statements_count"], 0)
        self.assertEqual(connection.statements, [])

    def test_cli_002_returns_nonzero_for_recorded_invalid_contract(self):
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
            tipos_lavado_composite_codigo_unique=True,
        )
        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=FakeEngine())

        with patch.dict(sys.modules, {"app.db.database": fake_database}):
            with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                with redirect_stdout(output):
                    exit_code = main([
                        "--apply-002-create-tipos-lavado", "--backup-confirmed", "--confirm-dev-db",
                        "--expected-database", "parking",
                    ])

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "invalid_contract")

    def test_002_retries_after_seed_or_record_failure_without_destructive_action(self):
        failed_seed = ApplyConnection(fail_seed=True)
        absent = _inventory(["schema_migrations"], migration_ids=["001_create_schema_migrations"])
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=absent):
            result = apply_002_create_tipos_lavado(FakeEngine(failed_seed), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "failed_after_create")
        retry = ApplyConnection()
        table_without_seed = _inventory(["schema_migrations", "tipos_lavado"], migration_ids=["001_create_schema_migrations"], tipos_lavado_seed=False)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=table_without_seed):
            result = apply_002_create_tipos_lavado(FakeEngine(retry), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual([statement for statement, _ in retry.statements], [MIGRATION_002_SEED_SQL, MIGRATION_001_RECORD_SQL])

        failed_record = ApplyConnection(fail_insert=True)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=table_without_seed):
            result = apply_002_create_tipos_lavado(FakeEngine(failed_record), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "failed_after_seed")
        retry_record = ApplyConnection()
        seed_present = _inventory(["schema_migrations", "tipos_lavado"], migration_ids=["001_create_schema_migrations"], tipos_lavado_seed=True)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=seed_present):
            result = apply_002_create_tipos_lavado(FakeEngine(retry_record), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(retry_record.statements, [(MIGRATION_001_RECORD_SQL, {"migration_id": "002_create_tipos_lavado"})])

    def test_cli_apply_requires_expected_database_before_importing_database(self):
        error = io.StringIO()

        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(["--apply-001-create-schema-migrations"])

        self.assertIn("--expected-database is required for apply", error.getvalue())

    def test_cli_002_apply_requires_flags_before_importing_database(self):
        error = io.StringIO()

        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(["--apply-002-create-tipos-lavado"])

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
    tipos_lavado_seed=None, tipos_lavado_valid=True, tipos_lavado_composite_codigo_unique=False,
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
    if any(table.casefold() == "tipos_lavado" for table in tables):
        if tipos_lavado_valid:
            inventory.setdefault("columns", []).extend([
                {"table_name": "tipos_lavado", "column_name": "id_tipo_lavado", "column_type": "int", "column_key": "PRI", "is_nullable": "NO", "extra": "auto_increment"},
                {"table_name": "tipos_lavado", "column_name": "codigo", "column_type": "varchar(50)", "column_key": "UNI", "is_nullable": "NO"},
                {"table_name": "tipos_lavado", "column_name": "nombre", "column_type": "varchar(80)", "is_nullable": "NO"},
                {"table_name": "tipos_lavado", "column_name": "activo", "column_type": "tinyint(1)", "column_default": "1", "is_nullable": "NO"},
                {"table_name": "tipos_lavado", "column_name": "created_at", "column_type": "datetime", "column_default": "CURRENT_TIMESTAMP", "is_nullable": "NO"},
                {"table_name": "tipos_lavado", "column_name": "updated_at", "column_type": "datetime", "column_default": "CURRENT_TIMESTAMP", "is_nullable": "NO", "extra": "on update CURRENT_TIMESTAMP"},
            ])
            inventory.setdefault("indexes", []).extend([
                {"table_name": "tipos_lavado", "index_name": "PRIMARY", "column_name": "id_tipo_lavado", "seq_in_index": 1, "non_unique": 0},
                {"table_name": "tipos_lavado", "index_name": "codigo", "column_name": "codigo", "seq_in_index": 1, "non_unique": 0},
            ])
            if tipos_lavado_composite_codigo_unique:
                inventory["indexes"][-1:] = [
                    {"table_name": "tipos_lavado", "index_name": "codigo_otra_columna", "column_name": "codigo", "seq_in_index": 1, "non_unique": 0},
                    {"table_name": "tipos_lavado", "index_name": "codigo_otra_columna", "column_name": "otra_columna", "seq_in_index": 2, "non_unique": 0},
                ]
        inventory["tipos_lavado_seed_snapshot"] = {
            "source_table": "tipos_lavado", "available": tipos_lavado_valid,
            "records": [{"codigo": "lavado_general", "nombre": "Modified", "activo": 0}] if tipos_lavado_seed else [],
        }
    return inventory


if __name__ == "__main__":
    unittest.main()
