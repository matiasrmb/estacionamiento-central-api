import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.db.schema_migration_runner import (
    MANAGED_MIGRATION_IDS,
    MIGRATIONS,
    MIGRATION_001_RECORD_SQL,
    MIGRATION_002_SEED_SQL,
    MIGRATION_003_ID,
    MIGRATION_004_ID,
    MIGRATION_005_ID,
    apply_001_create_schema_migrations,
    apply_002_create_tipos_lavado,
    apply_003_widen_pagos_mensuales_metodo_pago,
    apply_004_add_operaciones_servicio_ingreso_generado_fk,
    apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk,
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
    def __init__(self, *, fail_insert=False, fail_seed=False, fail_alter=False):
        self.statements = []
        self.fail_insert = fail_insert
        self.fail_seed = fail_seed
        self.fail_alter = fail_alter

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        if self.fail_alter and str(statement).startswith("ALTER TABLE"):
            raise RuntimeError("simulated alter failure")
        if self.fail_insert and "INSERT INTO schema_migrations" in str(statement):
            raise RuntimeError("simulated insert failure")
        if self.fail_seed and "INSERT INTO tipos_lavado" in str(statement):
            raise RuntimeError("simulated seed failure")


class SchemaMigrationRunnerTests(unittest.TestCase):
    def test_managed_migrations_use_full_logical_ids(self):
        self.assertEqual(MANAGED_MIGRATION_IDS, (
            "001_create_schema_migrations",
            "002_create_tipos_lavado",
            "003_widen_pagos_mensuales_metodo_pago",
            "004_add_operaciones_servicio_ingreso_generado_fk",
            "005_add_operaciones_servicio_tipo_vehiculo_lavado_fk",
        ))
        self.assertEqual(
            [migration.migration_id for migration in MIGRATIONS],
            list(MANAGED_MIGRATION_IDS),
        )
        self.assertNotIn("001", MANAGED_MIGRATION_IDS)
        self.assertNotIn("002", MANAGED_MIGRATION_IDS)
        self.assertNotIn("003", MANAGED_MIGRATION_IDS)
        self.assertNotIn("004", MANAGED_MIGRATION_IDS)
        self.assertNotIn("005", MANAGED_MIGRATION_IDS)

    def test_historical_002_sql_is_not_a_managed_migration_statement(self):
        historical_sql = (
            Path(__file__).resolve().parents[1]
            / "app" / "db" / "migrations" / "002_operaciones_servicio_state.sql"
        ).read_text(encoding="utf-8")

        self.assertNotIn(historical_sql, [statement for migration in MIGRATIONS for statement in migration.statements])

    def test_historical_002_full_id_does_not_mark_managed_002_as_applied(self):
        plan = plan_schema_migrations(_inventory(
            ["schema_migrations"],
            migration_ids=["001_create_schema_migrations", "002_operaciones_servicio_state"],
        ))

        self.assertEqual(plan["migrations"][1]["id"], "002_create_tipos_lavado")
        self.assertEqual(plan["migrations"][1]["status"], "pending")

    def test_historical_bare_002_does_not_mark_managed_002_as_applied(self):
        plan = plan_schema_migrations(_inventory(
            ["schema_migrations"],
            migration_ids=["001_create_schema_migrations", "002"],
        ))

        self.assertEqual(plan["migrations"][1]["id"], "002_create_tipos_lavado")
        self.assertEqual(plan["migrations"][1]["status"], "pending")

    def test_historical_005_or_bare_003_does_not_mark_managed_003_as_applied(self):
        for historical_id in ("005_monthly_payments", "003"):
            with self.subTest(historical_id=historical_id):
                plan = plan_schema_migrations(_inventory(
                    ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
                    migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado", historical_id],
                    metodo_pago_type="varchar(40)",
                ))

                self.assertEqual(plan["migrations"][2]["status"], "pending")

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

    def test_003_is_pending_for_safe_varchar_40_after_prerequisites(self):
        plan = plan_schema_migrations(_inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
            metodo_pago_type="varchar(40)",
        ))

        self.assertEqual(plan["migrations"][2]["status"], "pending")
        self.assertEqual(plan["migrations"][2]["sql"], [
            "ALTER TABLE pagos_mensuales MODIFY COLUMN metodo_pago VARCHAR(50) NULL",
            MIGRATION_001_RECORD_SQL,
        ])

    def test_003_is_blocked_when_either_prerequisite_is_missing(self):
        for migration_ids in ([], ["001_create_schema_migrations"]):
            with self.subTest(migration_ids=migration_ids):
                plan = plan_schema_migrations(_inventory(
                    ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
                    migration_ids=migration_ids,
                    metodo_pago_type="varchar(40)",
                ))
                self.assertEqual(plan["migrations"][2]["status"], "blocked_prerequisite")

    def test_003_applies_alter_then_record_for_safe_varchar_40(self):
        connection = ApplyConnection()
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
            metodo_pago_type="varchar(40)",
        )
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_003_widen_pagos_mensuales_metodo_pago(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(result["status"], "applied")
        self.assertEqual(connection.statements, [
            ("ALTER TABLE pagos_mensuales MODIFY COLUMN metodo_pago VARCHAR(50) NULL", None),
            (MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_003_ID}),
        ])

    def test_003_valid_unrecorded_repairs_by_recording_only(self):
        connection = ApplyConnection()
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
            metodo_pago_type="varchar(50)",
        )
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_003_widen_pagos_mensuales_metodo_pago(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["status"], "repaired")
        self.assertEqual(connection.statements, [(MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_003_ID})])

    def test_003_recorded_with_valid_column_noops(self):
        connection = ApplyConnection()
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID],
            metodo_pago_type="varchar(50)",
        )
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_003_widen_pagos_mensuales_metodo_pago(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["status"], "noop")
        self.assertEqual(connection.statements, [])

    def test_003_recorded_with_narrow_missing_or_incompatible_column_refuses(self):
        for metodo_pago_type in ("varchar(40)", None, "int"):
            with self.subTest(metodo_pago_type=metodo_pago_type):
                connection = ApplyConnection()
                inventory = _inventory(
                    ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
                    migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID],
                    metodo_pago_type=metodo_pago_type,
                )
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_003_widen_pagos_mensuales_metodo_pago(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

                self.assertIn(result["status"], {"refused", "invalid_contract"})
                self.assertEqual(result["executed_statements_count"], 0)
                self.assertEqual(connection.statements, [])

    def test_003_refuses_extra_or_nondefault_collation_without_sql(self):
        for overrides in (
            {"metodo_pago_extra": "INVISIBLE"},
            {"metodo_pago_collation": "utf8mb4_bin"},
            {"metodo_pago_character_set": "latin1"},
        ):
            with self.subTest(overrides=overrides):
                connection = ApplyConnection()
                inventory = _inventory(
                    ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
                    migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
                    metodo_pago_type="varchar(40)",
                    **overrides,
                )
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_003_widen_pagos_mensuales_metodo_pago(
                        FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
                    )

                self.assertEqual(result["status"], "invalid_contract")
                self.assertEqual(result["executed_statements_count"], 0)
                self.assertEqual(connection.statements, [])

    def test_003_alter_failure_reports_no_executed_alter(self):
        connection = ApplyConnection(fail_alter=True)
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
            metodo_pago_type="varchar(40)",
        )
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_003_widen_pagos_mensuales_metodo_pago(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["executed_statements_count"], 0)
        self.assertEqual(result["executed_statement_types"], [])
        self.assertEqual(len(connection.statements), 1)

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

    def test_cli_003_apply_requires_flags_before_importing_database(self):
        error = io.StringIO()

        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(["--apply-003-widen-pagos-mensuales-metodo-pago"])

        self.assertIn("--expected-database is required for apply", error.getvalue())

        error = io.StringIO()
        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(["--apply-003-widen-pagos-mensuales-metodo-pago", "--expected-database", "parking"])
        self.assertIn("--confirm-dev-db is required for apply", error.getvalue())

    def test_003_refuses_database_mismatch_without_sql(self):
        connection = ApplyConnection()
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado"],
            metodo_pago_type="varchar(40)",
        )
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_003_widen_pagos_mensuales_metodo_pago(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="other"
            )

        self.assertEqual(result["status"], "refused")
        self.assertEqual(connection.statements, [])

    def test_004_pending_apply_repair_noop_and_refusal_states(self):
        prerequisites = ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID]
        safe = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"],
            migration_ids=prerequisites, metodo_pago_type="varchar(50)",
        )
        plan = plan_schema_migrations(safe)
        migration = plan["migrations"][3]
        self.assertEqual(migration["status"], "pending")
        self.assertEqual(migration["sql"], [MIGRATIONS[3].statements[0], MIGRATION_001_RECORD_SQL])
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=safe):
            result = apply_004_add_operaciones_servicio_ingreso_generado_fk(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(connection.statements, [(MIGRATIONS[3].statements[0], None), (MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_004_ID})])

        present = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"],
            migration_ids=prerequisites, metodo_pago_type="varchar(50)", operaciones_fk_state="valid",
        )
        repair = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=present):
            result = apply_004_add_operaciones_servicio_ingreso_generado_fk(FakeEngine(repair), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(repair.statements, [(MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_004_ID})])

        recorded = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"],
            migration_ids=[*prerequisites, MIGRATION_004_ID], metodo_pago_type="varchar(50)", operaciones_fk_state="valid",
        )
        noop = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=recorded):
            result = apply_004_add_operaciones_servicio_ingreso_generado_fk(FakeEngine(noop), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "noop")
        self.assertEqual(noop.statements, [])

    def test_004_recorded_with_no_action_rules_is_applied_and_noops_without_sql(self):
        prerequisites = ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID]
        inventory = _inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"],
            migration_ids=[*prerequisites, MIGRATION_004_ID],
            metodo_pago_type="varchar(50)",
            operaciones_fk_state="valid",
            operaciones_fk_update_rule="NO ACTION",
            operaciones_fk_delete_rule="NO ACTION",
        )
        connection = ApplyConnection()
        plan = plan_schema_migrations(inventory)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_004_add_operaciones_servicio_ingreso_generado_fk(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )

        self.assertEqual(plan["migrations"][3]["status"], "applied")
        self.assertEqual(plan["migrations"][3]["sql"], [])
        self.assertEqual(result["status"], "noop")
        self.assertEqual(connection.statements, [])

    def test_004_refuses_missing_prerequisites_or_unsafe_contract_without_sql(self):
        tables = ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"]
        for migration_ids, overrides in (
            (["001_create_schema_migrations", "002_create_tipos_lavado"], {}),
            (["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID], {"operaciones_orphans": 1}),
            (["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID], {"operaciones_child_index": False}),
            (["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID], {"operaciones_fk_state": "wrong_target"}),
            (["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID], {"operaciones_fk_state": "wrong_rules"}),
            (["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID, MIGRATION_004_ID], {}),
        ):
            with self.subTest(migration_ids=migration_ids, overrides=overrides):
                connection = ApplyConnection()
                inventory = _inventory(tables, migration_ids=migration_ids, metodo_pago_type="varchar(50)", **overrides)
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_004_add_operaciones_servicio_ingreso_generado_fk(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
                self.assertIn(result["status"], {"refused", "invalid_contract"})
                self.assertEqual(connection.statements, [])

    def test_004_refuses_incompatible_types_engines_or_constraint_name_collision_without_sql(self):
        prerequisites = ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID]
        tables = ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"]
        for overrides in (
            {"operaciones_parent_type": "int unsigned"},
            {"operaciones_child_type": "int unsigned"},
            {"operaciones_child_type": "bigint"},
            {"operaciones_child_engine": "MyISAM"},
            {"operaciones_parent_engine": None},
            {"operaciones_fk_state": "name_collision"},
        ):
            with self.subTest(overrides=overrides):
                connection = ApplyConnection()
                inventory = _inventory(tables, migration_ids=prerequisites, metodo_pago_type="varchar(50)", **overrides)
                if overrides.get("operaciones_fk_state") == "name_collision":
                    inventory["foreign_keys"][0].update(table_name="other", column_name="other_id")
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_004_add_operaciones_servicio_ingreso_generado_fk(
                        FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
                    )
                self.assertIn(result["status"], {"refused", "invalid_contract"})
                self.assertEqual(result["executed_statements_count"], 0)
                self.assertEqual(connection.statements, [])

    def test_004_rejects_unsigned_child_and_parent_in_plan_apply_and_cli(self):
        prerequisites = ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID]
        tables = ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"]
        inventory = _inventory(
            tables,
            migration_ids=prerequisites,
            metodo_pago_type="varchar(50)",
            operaciones_child_type="int unsigned",
            operaciones_parent_type="int unsigned",
        )

        plan = plan_schema_migrations(inventory)
        migration = plan["migrations"][3]
        self.assertEqual(migration["status"], "invalid_contract")
        self.assertEqual(migration["sql"], [])
        self.assertFalse(plan["operaciones_servicio_ingreso_generado_fk"]["add_safe"])

        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_004_add_operaciones_servicio_ingreso_generado_fk(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )
        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(result["executed_statements_count"], 0)
        self.assertEqual(connection.statements, [])

        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=FakeEngine())
        with patch.dict(sys.modules, {"app.db.database": fake_database}):
            with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                with redirect_stdout(output):
                    exit_code = main([
                        "--apply-004-add-operaciones-servicio-ingreso-generado-fk", "--backup-confirmed",
                        "--confirm-dev-db", "--expected-database", "parking",
                    ])
        self.assertEqual(exit_code, 1)
        cli_result = json.loads(output.getvalue())
        self.assertEqual(cli_result["status"], "invalid_contract")
        self.assertEqual(cli_result["executed_statements_count"], 0)

    def test_004_record_failure_after_alter_is_reported_and_valid_fk_retries_record_only(self):
        prerequisites = ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID]
        tables = ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"]
        pending = _inventory(tables, migration_ids=prerequisites, metodo_pago_type="varchar(50)")
        failed_connection = ApplyConnection(fail_insert=True)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=pending):
            failure = apply_004_add_operaciones_servicio_ingreso_generado_fk(
                FakeEngine(failed_connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )
        self.assertEqual(failure["status"], "failed_after_alter")
        self.assertEqual(failure["executed_statement_types"], ["ALTER TABLE"])
        self.assertIn("may already be committed", failure["warnings"][0])
        self.assertIn("only if a fresh inventory sees the valid FK", failure["warnings"][1])

        valid_unrecorded = _inventory(tables, migration_ids=prerequisites, metodo_pago_type="varchar(50)", operaciones_fk_state="valid")
        retry_connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=valid_unrecorded):
            retry = apply_004_add_operaciones_servicio_ingreso_generado_fk(
                FakeEngine(retry_connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )
        self.assertEqual(retry["status"], "repaired")
        self.assertEqual(retry_connection.statements, [(MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_004_ID})])

    def test_historical_bare_004_does_not_count_as_managed_004(self):
        plan = plan_schema_migrations(_inventory(
            ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos"],
            migration_ids=["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID, "004"],
            metodo_pago_type="varchar(50)", operaciones_fk_state="valid",
        ))
        self.assertEqual(plan["migrations"][3]["status"], "repair_required")

    def test_cli_004_apply_requires_flags_before_importing_database(self):
        error = io.StringIO()
        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(["--apply-004-add-operaciones-servicio-ingreso-generado-fk"])
        self.assertIn("--expected-database is required for apply", error.getvalue())

    def test_005_pending_apply_repair_noop_and_refusal_states(self):
        prerequisites = ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID, MIGRATION_004_ID]
        tables = ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos", "tipos_vehiculo_lavado"]
        pending = _inventory(tables, migration_ids=prerequisites, metodo_pago_type="varchar(50)", operaciones_fk_state="valid")
        plan = plan_schema_migrations(pending)
        self.assertEqual(plan["migrations"][4]["status"], "pending")
        self.assertEqual(MIGRATIONS[4].statements[0], (
            "ALTER TABLE operaciones_servicio\n"
            "    ADD INDEX idx_operaciones_servicio_tipo_vehiculo_lavado (id_tipo_vehiculo_lavado),\n"
            "    ADD CONSTRAINT fk_operaciones_servicio_tipo_vehiculo_lavado\n"
            "        FOREIGN KEY (id_tipo_vehiculo_lavado)\n"
            "        REFERENCES tipos_vehiculo_lavado (id_tipo_vehiculo_lavado)"
        ))
        self.assertEqual(plan["migrations"][4]["sql"], [MIGRATIONS[4].statements[0], MIGRATION_001_RECORD_SQL])
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=pending):
            result = apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(connection.statements, [(MIGRATIONS[4].statements[0], None), (MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_005_ID})])

        valid = _inventory(tables, migration_ids=prerequisites, metodo_pago_type="varchar(50)", operaciones_fk_state="valid", tipo_vehiculo_lavado_fk_state="valid")
        repair = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=valid):
            result = apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(FakeEngine(repair), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(repair.statements, [(MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_005_ID})])

        recorded = _inventory(tables, migration_ids=[*prerequisites, MIGRATION_005_ID], metodo_pago_type="varchar(50)", operaciones_fk_state="valid", tipo_vehiculo_lavado_fk_state="valid", tipo_vehiculo_lavado_fk_rules=("NO ACTION", "NO ACTION"))
        noop = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=recorded):
            result = apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(FakeEngine(noop), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "noop")
        self.assertEqual(noop.statements, [])

    def test_005_refuses_missing_or_unsafe_contracts_without_sql(self):
        prerequisites = ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID, MIGRATION_004_ID]
        tables = ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos", "tipos_vehiculo_lavado"]
        for migration_ids, overrides in (
            (prerequisites[:-1], {}),
            (prerequisites, {"tipo_vehiculo_lavado_orphans": 1}),
            (prerequisites, {"tipo_vehiculo_lavado_child_engine": None}),
            (prerequisites, {"tipo_vehiculo_lavado_parent_engine": "MyISAM"}),
            (prerequisites, {"tipo_vehiculo_lavado_child_type": "int unsigned"}),
            (prerequisites, {"tipo_vehiculo_lavado_parent_type": "bigint"}),
            (prerequisites, {"tipo_vehiculo_lavado_parent_index": False}),
            (prerequisites, {"tipo_vehiculo_lavado_child_index": "exact"}),
            (prerequisites, {"tipo_vehiculo_lavado_child_index": "wrong"}),
            (prerequisites, {"tipo_vehiculo_lavado_fk_state": "wrong_target"}),
            (prerequisites, {"tipo_vehiculo_lavado_fk_state": "wrong_rules"}),
            ([*prerequisites, MIGRATION_005_ID], {}),
        ):
            with self.subTest(migration_ids=migration_ids, overrides=overrides):
                connection = ApplyConnection()
                inventory = _inventory(tables, migration_ids=migration_ids, metodo_pago_type="varchar(50)", operaciones_fk_state="valid", **overrides)
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
                self.assertIn(result["status"], {"refused", "invalid_contract"})
                self.assertEqual(connection.statements, [])

        missing_parent = _inventory(tables[:-1], migration_ids=prerequisites, metodo_pago_type="varchar(50)", operaciones_fk_state="valid")
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=missing_parent):
            result = apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(plan_schema_migrations(missing_parent)["migrations"][4]["status"], "blocked_prerequisite")
        self.assertEqual(result["status"], "refused")
        self.assertEqual(connection.statements, [])

        name_collision = _inventory(tables, migration_ids=prerequisites, metodo_pago_type="varchar(50)", operaciones_fk_state="valid")
        name_collision["foreign_keys"].append({
            "constraint_name": "fk_operaciones_servicio_tipo_vehiculo_lavado", "table_name": "other",
            "column_name": "other_id", "referenced_table_name": "other_parent", "referenced_column_name": "id",
            "update_rule": "RESTRICT", "delete_rule": "RESTRICT",
        })
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=name_collision):
            result = apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(connection.statements, [])

    def test_005_record_failure_and_bare_historical_id_retry_record_only(self):
        prerequisites = ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID, MIGRATION_004_ID]
        tables = ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos", "tipos_vehiculo_lavado"]
        pending = _inventory(tables, migration_ids=prerequisites, metodo_pago_type="varchar(50)", operaciones_fk_state="valid")
        failed = ApplyConnection(fail_insert=True)
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=pending):
            result = apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(FakeEngine(failed), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "failed_after_alter")
        self.assertEqual(result["executed_statement_types"], ["ALTER TABLE"])
        self.assertIn("may already be committed", result["warnings"][0])

        valid = _inventory(tables, migration_ids=[*prerequisites, "005"], metodo_pago_type="varchar(50)", operaciones_fk_state="valid", tipo_vehiculo_lavado_fk_state="valid")
        self.assertEqual(plan_schema_migrations(valid)["migrations"][4]["status"], "repair_required")
        retry = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=valid):
            result = apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(FakeEngine(retry), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(retry.statements, [(MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_005_ID})])

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
    metodo_pago_type=None, metodo_pago_nullable=True, metodo_pago_default=None,
    metodo_pago_extra="", metodo_pago_character_set="utf8mb4", metodo_pago_collation="utf8mb4_0900_ai_ci",
    operaciones_orphans=0, operaciones_child_index=True, operaciones_fk_state="absent",
    operaciones_fk_update_rule="RESTRICT", operaciones_fk_delete_rule="RESTRICT",
    operaciones_child_type="int", operaciones_parent_type="int", operaciones_child_engine="InnoDB", operaciones_parent_engine="InnoDB",
    tipo_vehiculo_lavado_orphans=0, tipo_vehiculo_lavado_child_index="absent", tipo_vehiculo_lavado_parent_index=True,
    tipo_vehiculo_lavado_fk_state="absent", tipo_vehiculo_lavado_fk_rules=("RESTRICT", "RESTRICT"),
    tipo_vehiculo_lavado_child_type="int", tipo_vehiculo_lavado_parent_type="int", tipo_vehiculo_lavado_child_engine="InnoDB", tipo_vehiculo_lavado_parent_engine="InnoDB",
):
    inventory = {
        "inventory_version": 1,
        "database": database,
        "tables": [{"table_name": table, "table_collation": "utf8mb4_0900_ai_ci"} for table in tables],
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
    if any(table.casefold() == "pagos_mensuales" for table in tables) and metodo_pago_type is not None:
        inventory.setdefault("columns", []).append({
            "table_name": "pagos_mensuales", "column_name": "metodo_pago",
            "data_type": "varchar" if metodo_pago_type.startswith("varchar") else metodo_pago_type,
            "column_type": metodo_pago_type,
            "is_nullable": "YES" if metodo_pago_nullable else "NO",
            "column_default": metodo_pago_default,
            "extra": metodo_pago_extra,
            "character_set_name": metodo_pago_character_set,
            "collation_name": metodo_pago_collation,
        })
    if any(table.casefold() == "operaciones_servicio" for table in tables):
        next(row for row in inventory["tables"] if row["table_name"].casefold() == "operaciones_servicio")["engine"] = operaciones_child_engine
        next(row for row in inventory["tables"] if row["table_name"].casefold() == "ingresos")["engine"] = operaciones_parent_engine
        inventory.setdefault("columns", []).append({"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "data_type": operaciones_child_type.split("(", 1)[0].split(" ", 1)[0], "column_type": operaciones_child_type, "is_nullable": "YES"})
        inventory.setdefault("columns", []).append({"table_name": "ingresos", "column_name": "id_ingreso", "data_type": operaciones_parent_type.split("(", 1)[0].split(" ", 1)[0], "column_type": operaciones_parent_type, "is_nullable": "NO", "column_key": "PRI"})
        inventory.setdefault("indexes", []).append({"table_name": "ingresos", "index_name": "PRIMARY", "column_name": "id_ingreso", "seq_in_index": 1, "non_unique": 0})
        if operaciones_child_index:
            inventory.setdefault("indexes", []).append({"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_ingreso_generado", "column_name": "id_ingreso_generado", "seq_in_index": 1, "non_unique": 1})
        if operaciones_fk_state != "absent":
            inventory["foreign_keys"] = [{"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "constraint_name": "fk_operaciones_servicio_ingreso_generado", "referenced_table_name": "ingresos" if operaciones_fk_state != "wrong_target" else "other", "referenced_column_name": "id_ingreso", "update_rule": "CASCADE" if operaciones_fk_state == "wrong_rules" else operaciones_fk_update_rule, "delete_rule": operaciones_fk_delete_rule}]
        inventory["operaciones_servicio_ingreso_generado_orphans"] = {"available": True, "count": operaciones_orphans}
    if any(table.casefold() == "tipos_vehiculo_lavado" for table in tables):
        next(row for row in inventory["tables"] if row["table_name"].casefold() == "operaciones_servicio")["engine"] = tipo_vehiculo_lavado_child_engine
        next(row for row in inventory["tables"] if row["table_name"].casefold() == "tipos_vehiculo_lavado")["engine"] = tipo_vehiculo_lavado_parent_engine
        inventory.setdefault("columns", []).extend([
            {"table_name": "operaciones_servicio", "column_name": "id_tipo_vehiculo_lavado", "data_type": tipo_vehiculo_lavado_child_type.split("(", 1)[0].split(" ", 1)[0], "column_type": tipo_vehiculo_lavado_child_type, "is_nullable": "YES"},
            {"table_name": "tipos_vehiculo_lavado", "column_name": "id_tipo_vehiculo_lavado", "data_type": tipo_vehiculo_lavado_parent_type.split("(", 1)[0].split(" ", 1)[0], "column_type": tipo_vehiculo_lavado_parent_type, "is_nullable": "NO", "column_key": "PRI"},
        ])
        if tipo_vehiculo_lavado_parent_index:
            inventory.setdefault("indexes", []).append({"table_name": "tipos_vehiculo_lavado", "index_name": "PRIMARY", "column_name": "id_tipo_vehiculo_lavado", "seq_in_index": 1, "non_unique": 0})
        if tipo_vehiculo_lavado_child_index == "exact" or tipo_vehiculo_lavado_fk_state != "absent":
            inventory.setdefault("indexes", []).append({"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_tipo_vehiculo_lavado", "column_name": "id_tipo_vehiculo_lavado", "seq_in_index": 1, "non_unique": 1})
        elif tipo_vehiculo_lavado_child_index == "wrong":
            inventory.setdefault("indexes", []).append({"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_tipo_vehiculo_lavado", "column_name": "other_id", "seq_in_index": 1, "non_unique": 1})
        if tipo_vehiculo_lavado_fk_state != "absent":
            update_rule, delete_rule = tipo_vehiculo_lavado_fk_rules
            inventory.setdefault("foreign_keys", []).append({
                "table_name": "operaciones_servicio", "column_name": "id_tipo_vehiculo_lavado", "constraint_name": "fk_operaciones_servicio_tipo_vehiculo_lavado",
                "referenced_table_name": "other" if tipo_vehiculo_lavado_fk_state == "wrong_target" else "tipos_vehiculo_lavado",
                "referenced_column_name": "id_tipo_vehiculo_lavado", "update_rule": "CASCADE" if tipo_vehiculo_lavado_fk_state == "wrong_rules" else update_rule, "delete_rule": delete_rule,
            })
        inventory["operaciones_servicio_tipo_vehiculo_lavado_orphans"] = {"available": True, "count": tipo_vehiculo_lavado_orphans}
    return inventory


if __name__ == "__main__":
    unittest.main()
