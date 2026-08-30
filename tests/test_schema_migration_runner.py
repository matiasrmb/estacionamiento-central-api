import io
import json
import sys
import tempfile
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
    MIGRATION_006_ID,
    MIGRATION_007_ID,
    apply_001_create_schema_migrations,
    apply_002_create_tipos_lavado,
    apply_003_widen_pagos_mensuales_metodo_pago,
    apply_004_add_operaciones_servicio_ingreso_generado_fk,
    apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk,
    apply_006_create_lavados_and_ingresos_en_lavado,
    apply_007_migrate_wash_vehicle_type_pricing,
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
            "006_create_lavados_and_ingresos_en_lavado",
            "007_migrate_wash_vehicle_type_pricing",
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
        from app.db.schema_migration_preflight import evaluate_schema_migration_preflight

        expected_plan = plan_schema_migrations(_inventory([]))
        expected_plan["preflight"] = evaluate_schema_migration_preflight(_inventory([]), expected_plan, {
            "backup_confirmed": False,
            "expected_database": None,
            "profile": None,
            "environment": None,
        })
        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=FakeEngine())

        with patch.dict(sys.modules, {"app.db.database": fake_database}):
            with patch(
                "app.db.schema_migration_runner.collect_dry_run_plan",
                return_value=expected_plan,
            ) as collect_plan:
                with redirect_stdout(output):
                    self.assertEqual(main(["--dry-run"]), 0)

        expected_output = {
            **expected_plan,
            "preflight": {
                key: value
                for key, value in expected_plan["preflight"].items()
                if key != "migration_plan"
            },
            "migrations": [
                {
                    "id": migration["id"],
                    "description": migration["description"],
                    "status": migration["status"],
                    "planned_statement_types": [sql.split(maxsplit=1)[0] for sql in migration["sql"]],
                    "will_execute": migration["will_execute"],
                }
                for migration in expected_plan["migrations"]
            ],
        }
        self.assertEqual(output.getvalue(), json.dumps(expected_output, indent=2, sort_keys=True) + "\n")
        collect_plan.assert_called_once_with(fake_database.engine, {
            "backup_confirmed": False,
            "expected_database": None,
            "profile": None,
            "environment": None,
        })

    def test_cli_dry_run_emits_installer_preflight_hash_without_sql(self):
        inventory = _inventory([])
        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=FakeEngine())
        with patch.dict(sys.modules, {"app.db.database": fake_database}):
            with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                with redirect_stdout(output):
                    self.assertEqual(main([
                        "--dry-run", "--profile", "installer-production", "--environment", "production",
                        "--expected-database", "parking", "--backup-confirmed",
                    ]), 0)

        result = json.loads(output.getvalue())
        self.assertEqual(result["preflight"]["runtime_context"]["profile"], "installer-production")
        self.assertEqual(result["preflight"]["runtime_context"]["environment"], "production")
        self.assertRegex(result["preflight"]["canonical_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("CREATE TABLE schema_migrations", output.getvalue())

    def test_installer_production_rejects_dev_confirmation_before_database_import(self):
        error = io.StringIO()

        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main([
                        "--apply-001-create-schema-migrations", "--profile", "installer-production",
                        "--environment", "production", "--expected-database", "parking",
                        "--confirm-dev-db",
                    ])

        self.assertIn("cannot be used", error.getvalue())

    def test_installer_production_requires_backup_and_preflight_before_database_import(self):
        base = [
            "--apply-001-create-schema-migrations", "--profile", "installer-production",
            "--environment", "production", "--expected-database", "parking", "--backup-confirmed",
        ]
        error = io.StringIO()
        with patch.dict(sys.modules, {"app.db.database": None}):
            with redirect_stderr(error):
                with self.assertRaisesRegex(SystemExit, "2"):
                    main(base)
        self.assertIn("--backup-path", error.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "backup.sql"
            backup.write_text("backup", encoding="utf-8")
            error = io.StringIO()
            with patch.dict(sys.modules, {"app.db.database": None}):
                with redirect_stderr(error):
                    with self.assertRaisesRegex(SystemExit, "2"):
                        main([*base, "--backup-path", str(backup)])
        self.assertIn("--preflight-sha256", error.getvalue())

    def test_installer_production_preflight_hash_mismatch_blocks_writes(self):
        connection = ApplyConnection()
        inventory = _inventory([])
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "backup.sql"
            backup.write_text("backup", encoding="utf-8")
            with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                result = apply_001_create_schema_migrations(
                    FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=False,
                    expected_database="parking", profile="installer-production", environment="production",
                    backup_path=str(backup), preflight_sha256="not-the-current-preflight",
                )

        self.assertEqual(result["status"], "refused")
        self.assertEqual(connection.statements, [])

    def test_installer_production_accepts_current_preflight_and_one_explicit_migration(self):
        from app.db.schema_migration_preflight import evaluate_schema_migration_preflight

        connection = ApplyConnection()
        inventory = _inventory([])
        preflight = evaluate_schema_migration_preflight(inventory, plan_schema_migrations(inventory), {
            "backup_confirmed": True, "expected_database": "parking",
            "profile": "installer-production", "environment": "production",
        })
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "backup.sql"
            backup.write_text("backup", encoding="utf-8")
            with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                result = apply_001_create_schema_migrations(
                    FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=False,
                    expected_database="parking", profile="installer-production", environment="production",
                    backup_path=str(backup), preflight_sha256=preflight["canonical_sha256"],
                )

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["executed_statement_types"], ["CREATE TABLE", "INSERT"])

    def test_installer_production_rejects_changed_006_plan_before_writes(self):
        from app.db.schema_migration_preflight import evaluate_schema_migration_preflight

        connection = ApplyConnection()
        approved_inventory = _inventory_006(lavados=None, en_lavado=False)
        current_inventory = _inventory_006(lavados="partial", en_lavado=False)
        preflight = evaluate_schema_migration_preflight(
            approved_inventory, plan_schema_migrations(approved_inventory), {
                "backup_confirmed": True, "expected_database": "parking",
                "profile": "installer-production", "environment": "production",
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "backup.sql"
            backup.write_text("backup", encoding="utf-8")
            with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=current_inventory):
                result = apply_006_create_lavados_and_ingresos_en_lavado(
                    FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=False,
                    expected_database="parking", profile="installer-production", environment="production",
                    backup_path=str(backup), preflight_sha256=preflight["canonical_sha256"],
                )

        self.assertEqual(result["status"], "refused")
        self.assertEqual(connection.statements, [])

    def test_cli_sanitizes_inventory_collection_failure(self):
        error = io.StringIO()
        fake_database = types.SimpleNamespace(engine=FakeEngine())
        failure = RuntimeError("mysql+pymysql://user:password@db-host:3306/parking")

        with patch.dict(sys.modules, {"app.db.database": fake_database}):
            with patch("app.db.schema_migration_runner.collect_dry_run_plan", side_effect=failure):
                with redirect_stderr(error):
                    self.assertEqual(main(["--dry-run"]), 1)

        self.assertIn("inventory could not be collected", error.getvalue())
        self.assertNotIn("mysql+pymysql", error.getvalue())
        self.assertNotIn("db-host", error.getvalue())
        self.assertNotIn("password", error.getvalue())

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

    def test_006_create_repair_noop_legacy_and_historical_prefix(self):
        fresh = _inventory_006()
        plan = plan_schema_migrations(fresh)
        self.assertEqual(plan["migrations"][5]["status"], "pending")
        self.assertIn("CREATE TABLE lavados", plan["migrations"][5]["sql"][0])
        self.assertIn("ALTER TABLE ingresos ADD COLUMN en_lavado TINYINT(1) DEFAULT 0", plan["migrations"][5]["sql"])
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=fresh):
            result = apply_006_create_lavados_and_ingresos_en_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["executed_statement_types"], ["CREATE TABLE", "ALTER TABLE", "INSERT migration record"])

        complete = _inventory_006(lavados="complete", en_lavado=True, migration_ids=[*_migration_006_prerequisites(), "006_cobros_noches"])
        self.assertEqual(plan_schema_migrations(complete)["migrations"][5]["status"], "repair_required")
        repair = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=complete):
            result = apply_006_create_lavados_and_ingresos_en_lavado(FakeEngine(repair), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(repair.statements, [(MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_006_ID})])

        registered = _inventory_006(lavados="complete", en_lavado=True, migration_ids=[*_migration_006_prerequisites(), MIGRATION_006_ID])
        self.assertEqual(plan_schema_migrations(registered)["migrations"][5]["status"], "applied")

        legacy = _inventory_006(lavados="legacy", en_lavado=True)
        self.assertEqual(plan_schema_migrations(legacy)["migrations"][5]["status"], "pending")
        self.assertIn("ADD COLUMN id_tipo_vehiculo_lavado INT NULL", plan_schema_migrations(legacy)["migrations"][5]["sql"][0])

    def test_006_refuses_orphans_divergent_foreign_keys_and_engine_without_sql(self):
        for override in ("orphans", "wrong_fk", "additional_wrong_fk", "engine", "name_collision"):
            with self.subTest(override=override):
                inventory = _inventory_006(lavados="complete", en_lavado=True)
                if override == "orphans":
                    inventory["foreign_keys"] = [row for row in inventory["foreign_keys"] if row["table_name"] != "lavados" or row["column_name"] != "id_ingreso"]
                    inventory["lavados_orphans"]["ingreso"]["count"] = 1
                elif override == "wrong_fk":
                    next(row for row in inventory["foreign_keys"] if row["table_name"] == "lavados" and row["column_name"] == "id_ingreso")["referenced_table_name"] = "other"
                elif override == "additional_wrong_fk":
                    inventory["foreign_keys"].append({"constraint_name": "generated_wrong_ingreso", "table_name": "lavados", "column_name": "id_ingreso", "referenced_table_name": "other", "referenced_column_name": "id", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"})
                elif override == "name_collision":
                    inventory["foreign_keys"].append({"constraint_name": "fk_lavados_ingreso", "table_name": "other", "column_name": "other_id", "referenced_table_name": "other_parent", "referenced_column_name": "id", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"})
                else:
                    next(row for row in inventory["tables"] if row["table_name"] == "lavados")["engine"] = "MyISAM"
                plan = plan_schema_migrations(inventory)
                self.assertEqual(plan["migrations"][5]["status"], "invalid_contract")
                self.assertEqual(plan["migrations"][5]["sql"], [])
                connection = ApplyConnection()
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_006_create_lavados_and_ingresos_en_lavado(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
                self.assertIn(result["status"], {"refused", "invalid_contract"})
                self.assertEqual(connection.statements, [])

    def test_006_legacy_refuses_external_vehicle_type_fk_name_collision_without_sql(self):
        inventory = _inventory_006(lavados="legacy", en_lavado=True)
        inventory["foreign_keys"].append({
            "constraint_name": "fk_lavados_tipo_vehiculo_lavado",
            "table_name": "external_child",
            "column_name": "external_parent_id",
            "referenced_table_name": "external_parent",
            "referenced_column_name": "id",
            "update_rule": "RESTRICT",
            "delete_rule": "RESTRICT",
        })

        plan = plan_schema_migrations(inventory)

        self.assertEqual(plan["migrations"][5]["status"], "invalid_contract")
        self.assertEqual(plan["migrations"][5]["sql"], [])
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_006_create_lavados_and_ingresos_en_lavado(
                FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking"
            )
        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(result["executed_statement_types"], [])
        self.assertEqual(connection.statements, [])

    def test_007_copies_plural_then_overrides_known_prices_from_config(self):
        inventory = _inventory_007(canonical=False, plural=True, config_values={"lavado_suv": "9000"})

        plan = plan_schema_migrations(inventory)
        migration = plan["migrations"][6]

        self.assertEqual(migration["status"], "pending")
        self.assertIn("CREATE TABLE tipos_vehiculo_lavado", migration["sql"][0])
        self.assertIn("FROM tipos_vehiculos_lavado", migration["sql"][1])
        self.assertIn("'lavado_suv', 'SUV', 9000, 1", migration["sql"][3])
        self.assertIn("ON DUPLICATE KEY UPDATE", migration["sql"][3])

    def test_007_existing_canonical_only_inserts_missing_known_codes_and_then_noops(self):
        inventory = _inventory_007(canonical=True, canonical_records=[{"codigo": "lavado_citycar", "nombre": "Administrado", "valor_lavado": 7777, "activo": 0}], config_values={"lavado_citycar": "9000", "lavado_suv": "8500"})
        plan = plan_schema_migrations(inventory)
        migration = plan["migrations"][6]

        self.assertEqual(migration["status"], "pending")
        self.assertFalse(any("lavado_citycar" in statement for statement in migration["sql"]))
        self.assertIn("'lavado_suv', 'SUV', 8500, 1", migration["sql"][0])
        connection = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_007_migrate_wash_vehicle_type_pricing(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(connection.statements[-1], (MIGRATION_001_RECORD_SQL, {"migration_id": MIGRATION_007_ID}))

        inventory["wash_vehicle_type_snapshots"]["tipos_vehiculo_lavado"]["records"] = [
            {"codigo": code, "nombre": name, "valor_lavado": value, "activo": 1}
            for code, name, value in (("lavado_citycar", "Administrado", 7777), ("lavado_suv", "SUV", 8500), ("lavado_camioneta", "Camioneta", 10000), ("lavado_furgon", "Furgón", 15000), ("lavado_minibus", "Mini bus o vehículos grandes", 25000))
        ]
        inventory["migration_snapshot"]["records"].append({"migration_id": MIGRATION_007_ID})
        self.assertEqual(plan_schema_migrations(inventory)["migrations"][6]["status"], "applied")
        noop = ApplyConnection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_007_migrate_wash_vehicle_type_pricing(FakeEngine(noop), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "noop")
        self.assertEqual(noop.statements, [])

    def test_007_blocks_invalid_config_and_ambiguous_codes_before_sql(self):
        for records, config_values in (([{"codigo": "lavado_suv"}, {"codigo": "lavado_suv"}], {}), ([], {"lavado_suv": "0"})):
            with self.subTest(records=records, config_values=config_values):
                inventory = _inventory_007(canonical=True, canonical_records=records, config_values=config_values)
                connection = ApplyConnection()
                self.assertEqual(plan_schema_migrations(inventory)["migrations"][6]["status"], "invalid_contract")
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_007_migrate_wash_vehicle_type_pricing(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
                self.assertIn(result["status"], {"invalid_contract", "refused"})
                self.assertEqual(connection.statements, [])

    def test_007_rejects_non_integer_config_values_before_sql(self):
        for value in (
            "9000.5", "NaN", "Infinity", "-Infinity", "not-a-number", "0", "-1",
            float("nan"), float("inf"), float("-inf"), 0, -1, True,
        ):
            with self.subTest(value=value):
                inventory = _inventory_007(canonical=True, config_values={"lavado_suv": value})
                connection = ApplyConnection()

                self.assertEqual(plan_schema_migrations(inventory)["migrations"][6]["status"], "invalid_contract")
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_007_migrate_wash_vehicle_type_pricing(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

                self.assertIn(result["status"], {"invalid_contract", "refused"})
                self.assertEqual(connection.statements, [])

    def test_007_preserves_positive_integer_config_strings_and_ints(self):
        for value in ("9000", 9000):
            with self.subTest(value=value):
                inventory = _inventory_007(canonical=True, config_values={"lavado_suv": value})

                migration = plan_schema_migrations(inventory)["migrations"][6]

                self.assertEqual(migration["status"], "pending")
                self.assertIn("'lavado_suv', 'SUV', 9000, 1", migration["sql"][1])

    def test_007_normalises_case_and_surrounding_space_for_known_codes(self):
        inventory = _inventory_007(
            canonical=True,
            canonical_records=[{"codigo": " LAVADO_SUV ", "nombre": "SUV", "valor_lavado": 8000, "activo": 1}],
            config_values=[(" LAVADO_CITYCAR ", "9000")],
        )

        migration = plan_schema_migrations(inventory)["migrations"][6]

        self.assertEqual(migration["status"], "pending")
        self.assertFalse(any("'lavado_suv'" in statement for statement in migration["sql"]))
        self.assertIn("'lavado_citycar', 'CityCar', 9000, 1", migration["sql"][0])

    def test_007_rejects_case_and_space_equivalent_duplicate_codes_before_sql(self):
        inventory = _inventory_007(
            canonical=True,
            canonical_records=[{"codigo": "lavado_suv"}, {"codigo": " LAVADO_SUV "}],
            config_values=[("lavado_citycar", "5000"), (" LAVADO_CITYCAR ", "6000")],
        )
        connection = ApplyConnection()

        self.assertEqual(plan_schema_migrations(inventory)["migrations"][6]["status"], "invalid_contract")
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_007_migrate_wash_vehicle_type_pricing(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertIn(result["status"], {"invalid_contract", "refused"})
        self.assertEqual(connection.statements, [])

    def test_007_rejects_incompatible_plural_source_before_sql(self):
        inventory = _inventory_007(canonical=False, plural=True)
        inventory["columns"] = [
            row for row in inventory["columns"]
            if not (row["table_name"] == "tipos_vehiculos_lavado" and row["column_name"] == "valor_lavado")
        ]
        connection = ApplyConnection()

        self.assertEqual(plan_schema_migrations(inventory)["migrations"][6]["status"], "invalid_contract")
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_007_migrate_wash_vehicle_type_pricing(FakeEngine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")

        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(connection.statements, [])

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


def _migration_006_prerequisites():
    return ["001_create_schema_migrations", "002_create_tipos_lavado", MIGRATION_003_ID, MIGRATION_004_ID, MIGRATION_005_ID]


def _inventory_006(*, lavados=None, en_lavado=False, migration_ids=None):
    inventory = _inventory(
        ["schema_migrations", "tipos_lavado", "pagos_mensuales", "operaciones_servicio", "ingresos", "tipos_vehiculo_lavado", "vehiculos", *( ["lavados"] if lavados else [])],
        migration_ids=_migration_006_prerequisites() if migration_ids is None else migration_ids,
        metodo_pago_type="varchar(50)", operaciones_fk_state="valid", tipo_vehiculo_lavado_fk_state="valid",
    )
    vehiculos = next(row for row in inventory["tables"] if row["table_name"] == "vehiculos")
    vehiculos["engine"] = "InnoDB"
    inventory["columns"].append({"table_name": "vehiculos", "column_name": "id_vehiculo", "data_type": "int", "column_type": "int", "is_nullable": "NO", "column_key": "PRI", "extra": "auto_increment", "column_default": None})
    inventory["indexes"].append({"table_name": "vehiculos", "index_name": "PRIMARY", "column_name": "id_vehiculo", "seq_in_index": 1, "non_unique": 0})
    if en_lavado:
        inventory["columns"].append({"table_name": "ingresos", "column_name": "en_lavado", "data_type": "tinyint", "column_type": "tinyint(1)", "is_nullable": "YES", "column_default": "0", "extra": ""})
    inventory["lavados_orphans"] = {key: {"available": True, "count": 0} for key in ("ingreso", "vehiculo", "tipo_vehiculo_lavado")}
    if lavados:
        next(row for row in inventory["tables"] if row["table_name"] == "lavados")["engine"] = "InnoDB"
        columns = [
            ("id_lavado", "int", "NO", None, "PRI", "auto_increment"), ("id_ingreso", "int", "NO", None, "", ""),
            ("id_vehiculo", "int", "NO", None, "", ""), ("patente", "varchar(10)", "NO", None, "", ""),
            ("categoria_lavado", "varchar(50)", "NO", None, "", ""), ("valor_lavado", "int", "NO", None, "", ""),
            ("fecha_hora_inicio", "datetime", "NO", None, "", ""), ("fecha_hora_fin", "datetime", "YES", None, "", ""),
            ("usuario_inicio", "varchar(50)", "NO", None, "", ""), ("usuario_fin", "varchar(50)", "YES", None, "", ""), ("estado", "enum('activo','finalizado')", "NO", "activo", "", ""),
        ]
        if lavados == "complete":
            columns[6:6] = [("id_tipo_vehiculo_lavado", "int", "YES", None, "", ""), ("tipo_vehiculo_lavado_snapshot", "varchar(80)", "YES", None, "", "")]
        inventory["columns"].extend({"table_name": "lavados", "column_name": name, "data_type": column_type.split("(", 1)[0], "column_type": column_type, "is_nullable": nullable, "column_default": default, "column_key": key, "extra": extra} for name, column_type, nullable, default, key, extra in columns)
        inventory["indexes"].append({"table_name": "lavados", "index_name": "PRIMARY", "column_name": "id_lavado", "seq_in_index": 1, "non_unique": 0})
        foreign_keys = [
            ("ingreso", "id_ingreso", "ingresos", "id_ingreso"),
            ("vehiculo", "id_vehiculo", "vehiculos", "id_vehiculo"),
        ]
        if lavados == "complete":
            foreign_keys.append(("tipo_vehiculo_lavado", "id_tipo_vehiculo_lavado", "tipos_vehiculo_lavado", "id_tipo_vehiculo_lavado"))
        for suffix, child, parent_table, parent in foreign_keys:
            inventory.setdefault("foreign_keys", []).append({"table_name": "lavados", "column_name": child, "constraint_name": f"generated_{suffix}", "referenced_table_name": parent_table, "referenced_column_name": parent, "update_rule": "RESTRICT", "delete_rule": "RESTRICT"})
    return inventory


def _inventory_007(*, canonical, plural=False, canonical_records=None, config_values=None):
    inventory = _inventory_006(lavados="complete", en_lavado=True, migration_ids=[*_migration_006_prerequisites(), MIGRATION_006_ID])
    if not canonical:
        inventory["tables"] = [row for row in inventory["tables"] if row["table_name"] != "tipos_vehiculo_lavado"]
        inventory["columns"] = [row for row in inventory["columns"] if row["table_name"] != "tipos_vehiculo_lavado"]
        inventory["indexes"] = [row for row in inventory["indexes"] if row["table_name"] != "tipos_vehiculo_lavado"]
    if plural:
        inventory["tables"].append({"table_name": "tipos_vehiculos_lavado", "table_collation": "utf8mb4_0900_ai_ci"})
    tables = {row["table_name"] for row in inventory["tables"]}
    config_items = (config_values or {}).items() if isinstance(config_values, dict) else config_values or []
    inventory["config_seed_snapshot"] = {"available": True, "values": [{"clave": key, "valor": value} for key, value in config_items]}
    inventory["wash_vehicle_type_snapshots"] = {}
    for table_name, records in (("tipos_vehiculo_lavado", canonical_records or []), ("tipos_vehiculos_lavado", [{"codigo": "lavado_suv", "nombre": "Plural", "valor_lavado": 7000, "activo": 1}])):
        if table_name not in tables:
            continue
        table = next(row for row in inventory["tables"] if row["table_name"] == table_name)
        table["engine"] = "InnoDB"
        inventory["columns"] = [row for row in inventory.get("columns", []) if row.get("table_name") != table_name]
        inventory["indexes"] = [row for row in inventory.get("indexes", []) if row.get("table_name") != table_name]
        inventory["columns"].extend([
            {"table_name": table_name, "column_name": "id_tipo_vehiculo_lavado", "data_type": "int", "column_type": "int", "is_nullable": "NO", "extra": "auto_increment"},
            {"table_name": table_name, "column_name": "codigo", "column_type": "varchar(50)", "is_nullable": "NO"},
            {"table_name": table_name, "column_name": "nombre", "column_type": "varchar(80)", "is_nullable": "NO"},
            {"table_name": table_name, "column_name": "valor_lavado", "column_type": "int", "is_nullable": "NO"},
            {"table_name": table_name, "column_name": "activo", "column_type": "tinyint(1)", "is_nullable": "NO", "column_default": "1"},
            {"table_name": table_name, "column_name": "created_at", "column_type": "datetime", "is_nullable": "NO", "column_default": "CURRENT_TIMESTAMP"},
            {"table_name": table_name, "column_name": "updated_at", "column_type": "datetime", "is_nullable": "NO", "column_default": "CURRENT_TIMESTAMP", "extra": "on update CURRENT_TIMESTAMP"},
        ])
        inventory["indexes"].extend([
            {"table_name": table_name, "index_name": "PRIMARY", "column_name": "id_tipo_vehiculo_lavado", "seq_in_index": 1, "non_unique": 0},
            {"table_name": table_name, "index_name": "codigo", "column_name": "codigo", "seq_in_index": 1, "non_unique": 0},
        ])
        inventory["wash_vehicle_type_snapshots"][table_name] = {"available": True, "records": records}
    return inventory


if __name__ == "__main__":
    unittest.main()
