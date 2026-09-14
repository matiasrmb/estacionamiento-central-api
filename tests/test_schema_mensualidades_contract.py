import io
import json
import types
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from unittest.mock import patch

from app.db.schema_inventory import pagos_mensuales_contract
from app.db.schema_migration_preflight import evaluate_schema_migration_preflight
from app.db.schema_migration_runner import (
    MIGRATION_012_ID,
    apply_001_create_schema_migrations,
    apply_012_manage_mensualidades_contract,
    main,
    plan_schema_migrations,
)


PREREQUISITES = [
    "001_create_schema_migrations", "002_create_tipos_lavado",
    "003_widen_pagos_mensuales_metodo_pago",
    "004_add_operaciones_servicio_ingreso_generado_fk",
    "005_add_operaciones_servicio_tipo_vehiculo_lavado_fk",
    "006_create_lavados_and_ingresos_en_lavado",
    "007_migrate_wash_vehicle_type_pricing",
    "008_complete_operaciones_servicio_contract",
    "009_add_cierres_solo_lavado_totals",
    "010_add_asistencias_device_sessions", "011_manage_noches_contract",
]


class Connection:
    def __init__(self):
        self.statements = []

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, statement, params=None): self.statements.append((str(statement), params))


class Engine:
    def __init__(self, connection): self.connection = connection
    def begin(self): return self.connection


class MensualidadesContractTests(unittest.TestCase):
    def test_complete_contract_is_repair_required_or_applied(self):
        inventory = _inventory()
        self.assertTrue(pagos_mensuales_contract(inventory)["valid"])
        self.assertEqual(_migration(inventory)["status"], "repair_required")
        inventory["migration_snapshot"]["records"].append({"migration_id": MIGRATION_012_ID})
        self.assertEqual(_migration(inventory)["status"], "applied")

    def test_missing_table_and_additive_elements_plan_only_safe_ddl(self):
        inventory = _inventory(missing=("pagos_mensuales", "telefono", "total_mensualidades_monto"))
        migration = _migration(inventory)
        self.assertEqual(migration["status"], "pending")
        sql = "\n".join(migration["sql"])
        self.assertIn("CREATE TABLE pagos_mensuales", sql)
        self.assertIn(") ENGINE=InnoDB", sql)
        self.assertIn("ADD COLUMN telefono VARCHAR(30) NULL DEFAULT NULL", sql)
        self.assertIn("ADD COLUMN total_mensualidades_monto INT NOT NULL DEFAULT 0", sql)
        self.assertNotRegex(sql, r"(?i)DROP|UPDATE|DELETE")

    def test_partial_table_adds_columns_indexes_and_foreign_keys(self):
        inventory = _inventory(missing=("observacion", "idx_pagos_mensuales_periodo", "fk_pagos_mensuales_cierre"))
        migration = _migration(inventory)
        self.assertEqual(migration["status"], "pending")
        self.assertIn("ADD COLUMN observacion VARCHAR(500) NULL", migration["sql"][0])
        self.assertIn("ADD INDEX idx_pagos_mensuales_periodo (periodo)", migration["sql"][0])
        self.assertIn("ADD CONSTRAINT fk_pagos_mensuales_cierre", migration["sql"][0])

    def test_nonempty_partial_table_with_missing_required_column_blocks_before_sql(self):
        for missing in ("dia_vencimiento_snapshot", "created_at", "id_pago_mensual"):
            with self.subTest(missing=missing):
                inventory = _inventory(missing=(missing,))
                inventory["pagos_mensuales_row_count"] = {"available": True, "count": 1}
                connection = Connection()

                migration = _migration(inventory)
                with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
                    result = apply_012_manage_mensualidades_contract(
                        Engine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking",
                    )

                self.assertEqual(migration["status"], "invalid_contract")
                self.assertEqual(migration["sql"], [])
                self.assertEqual(result["status"], "invalid_contract")
                self.assertEqual(connection.statements, [])
                self.assertIn("missing required NOT NULL columns", pagos_mensuales_contract(inventory)["issues"][0])

    def test_empty_partial_table_can_add_missing_required_column(self):
        for missing, clause in (
            ("dia_vencimiento_snapshot", "ADD COLUMN dia_vencimiento_snapshot TINYINT UNSIGNED NOT NULL"),
            ("created_at", "ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ("id_pago_mensual", "ADD COLUMN id_pago_mensual INT AUTO_INCREMENT PRIMARY KEY"),
        ):
            with self.subTest(missing=missing):
                inventory = _inventory(missing=(missing,))
                inventory["pagos_mensuales_row_count"] = {"available": True, "count": 0}

                migration = _migration(inventory)

                self.assertEqual(migration["status"], "pending")
                self.assertIn(clause, migration["sql"][0])

    def test_prerequisites_duplicates_and_orphans_block_before_sql(self):
        for mutate, issue in (
            (lambda value: value["migration_snapshot"].update(records=[]), None),
            (lambda value: value.update(pagos_mensuales_duplicates={"available": True, "count": 1}), "duplicate"),
            (lambda value: value.update(pagos_mensuales_orphans={"vehiculo": {"available": True, "count": 1}, "cierre": {"available": True, "count": 0}}), "orphan"),
        ):
            with self.subTest(issue=issue):
                inventory = _inventory(missing=("uq_pagos_mensuales_vehiculo_periodo", "fk_pagos_mensuales_vehiculo"))
                mutate(inventory)
                migration = _migration(inventory)
                self.assertEqual(migration["sql"], [])
                self.assertEqual(migration["status"], "blocked_prerequisite" if issue is None else "invalid_contract")
                if issue is not None:
                    preflight = evaluate_schema_migration_preflight(inventory, plan_schema_migrations(inventory))
                    self.assertIn("pagos_mensuales.(id_vehiculo, periodo) duplicates" if issue == "duplicate" else "pagos_mensuales.id_vehiculo", preflight["orphan_blockers"])

    def test_012_data_blockers_do_not_block_applying_001(self):
        inventory = _inventory(missing=("uq_pagos_mensuales_vehiculo_periodo", "fk_pagos_mensuales_vehiculo"))
        inventory["migration_snapshot"]["records"] = []
        inventory["pagos_mensuales_duplicates"] = {"available": True, "count": 1}
        connection = Connection()

        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_001_create_schema_migrations(
                Engine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking",
            )

        self.assertEqual(_migration(inventory)["status"], "blocked_prerequisite")
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(connection.statements[-1][1], {"migration_id": "001_create_schema_migrations"})

    def test_incompatible_shapes_and_legacy_extra_index(self):
        for mutate in (
            lambda value: _column(value, "dia_vencimiento").update(column_type="tinyint(1)"),
            lambda value: _column(value, "metodo_pago").update(column_default="cash"),
            lambda value: _index(value, "idx_pagos_mensuales_periodo").update(column_name="fecha_pago"),
            lambda value: _fk(value, "fk_pagos_mensuales_vehiculo").update(delete_rule="CASCADE"),
            lambda value: _table(value, "pagos_mensuales").update(engine="MyISAM"),
            lambda value: _column(value, "id_vehiculo").update(column_type="int unsigned"),
        ):
            inventory = _inventory()
            mutate(inventory)
            self.assertEqual(_migration(inventory)["status"], "invalid_contract")
        inventory = _inventory()
        inventory["indexes"].append({"table_name": "pagos_mensuales", "index_name": "legacy_extra", "column_name": "usuario", "seq_in_index": 1, "non_unique": 1})
        self.assertEqual(_migration(inventory)["status"], "repair_required")

    def test_extra_foreign_key_blocks_before_sql(self):
        inventory = _inventory()
        inventory["foreign_keys"].append({
            "constraint_name": "fk_pagos_mensuales_usuario", "table_name": "pagos_mensuales",
            "column_name": "usuario", "referenced_table_name": "usuarios",
            "referenced_column_name": "usuario", "update_rule": "RESTRICT", "delete_rule": "RESTRICT",
        })
        connection = Connection()

        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_012_manage_mensualidades_contract(
                Engine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking",
            )

        self.assertEqual(_migration(inventory)["status"], "invalid_contract")
        self.assertEqual(_migration(inventory)["sql"], [])
        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(connection.statements, [])

    def test_empty_partial_table_with_alternate_primary_key_blocks_before_sql(self):
        inventory = _inventory(missing=("id_pago_mensual",))
        inventory["indexes"] = [
            row for row in inventory["indexes"]
            if not (row["table_name"] == "pagos_mensuales" and row["index_name"] == "PRIMARY")
        ]
        inventory["indexes"].append({
            "table_name": "pagos_mensuales", "index_name": "PRIMARY", "column_name": "usuario",
            "seq_in_index": 1, "non_unique": 0,
        })
        connection = Connection()

        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory):
            result = apply_012_manage_mensualidades_contract(
                Engine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking",
            )

        self.assertEqual(_migration(inventory)["status"], "invalid_contract")
        self.assertEqual(_migration(inventory)["sql"], [])
        self.assertEqual(result["status"], "invalid_contract")
        self.assertEqual(connection.statements, [])

    def test_canonical_foreign_keys_and_legacy_extra_indexes_are_tolerated(self):
        inventory = _inventory()
        inventory["indexes"].append({"table_name": "pagos_mensuales", "index_name": "legacy_extra", "column_name": "usuario", "seq_in_index": 1, "non_unique": 1})
        self.assertTrue(pagos_mensuales_contract(inventory)["valid"])
        self.assertEqual(_migration(inventory)["status"], "repair_required")

    def test_canonical_foreign_keys_accept_no_action_and_reject_unsafe_rules(self):
        inventory = _inventory()
        for foreign_key in inventory["foreign_keys"]:
            foreign_key.update(update_rule="NO ACTION", delete_rule="NO ACTION")
        self.assertTrue(pagos_mensuales_contract(inventory)["valid"])
        self.assertEqual(_migration(inventory)["status"], "repair_required")

        for rule in ("CASCADE", "SET NULL", "SET DEFAULT"):
            for field in ("update_rule", "delete_rule"):
                with self.subTest(rule=rule, field=field):
                    inventory = _inventory()
                    _fk(inventory, "fk_pagos_mensuales_vehiculo").update(**{field: rule})
                    self.assertFalse(pagos_mensuales_contract(inventory)["valid"])
                    self.assertEqual(_migration(inventory)["status"], "invalid_contract")

    def test_extra_foreign_key_on_canonical_column_is_invalid(self):
        inventory = _inventory()
        inventory["foreign_keys"].append({"constraint_name": "fk_legacy_pagos_mensuales_vehiculo", "table_name": "pagos_mensuales", "column_name": "id_vehiculo", "referenced_table_name": "vehiculos", "referenced_column_name": "id_vehiculo", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"})
        self.assertEqual(_migration(inventory)["status"], "invalid_contract")

    def test_preflight_hash_binds_contract_sql_duplicates_and_orphans(self):
        inventory = _inventory(missing=("idx_pagos_mensuales_periodo",))
        baseline = evaluate_schema_migration_preflight(inventory, plan_schema_migrations(inventory), {"profile": "installer-production", "environment": "production", "expected_database": "parking"})
        changed = deepcopy(inventory)
        changed["pagos_mensuales_duplicates"] = {"available": True, "count": 1}
        changed["indexes"] = [row for row in changed["indexes"] if row["index_name"] != "uq_pagos_mensuales_vehiculo_periodo"]
        altered = evaluate_schema_migration_preflight(changed, plan_schema_migrations(changed), {"profile": "installer-production", "environment": "production", "expected_database": "parking"})
        self.assertNotEqual(baseline["canonical_sha256"], altered["canonical_sha256"])

    def test_apply_registers_only_after_ddl_and_cli_dispatches(self):
        inventory = _inventory(missing=("telefono",))
        connection = Connection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory), patch("app.db.schema_migration_preflight.evaluate_schema_migration_preflight", return_value={"checks": []}):
            result = apply_012_manage_mensualidades_contract(Engine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "applied")
        self.assertIn("ALTER TABLE vehiculos", connection.statements[0][0])
        self.assertEqual(connection.statements[-1][1], {"migration_id": MIGRATION_012_ID})
        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=Engine(connection))
        with patch.dict("sys.modules", {"app.db.database": fake_database}), patch("app.db.schema_migration_runner.apply_012_manage_mensualidades_contract", return_value={"status": "noop"}) as apply, redirect_stdout(output):
            self.assertEqual(main(["--apply-012-manage-mensualidades-contract", "--backup-confirmed", "--confirm-dev-db", "--expected-database", "parking"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"status": "noop"})
        apply.assert_called_once()


def _migration(inventory):
    return next(item for item in plan_schema_migrations(inventory)["migrations"] if item["id"] == MIGRATION_012_ID)


def _inventory(missing=()):
    tables = ["schema_migrations", "vehiculos", "cierres_diarios"] + ([] if "pagos_mensuales" in missing else ["pagos_mensuales"])
    inventory = {"database": "parking", "tables": [{"table_name": name, "engine": "InnoDB", "table_collation": "utf8mb4_0900_ai_ci"} for name in tables], "columns": [], "indexes": [], "foreign_keys": [], "migration_snapshot": {"available": True, "records": [{"migration_id": item} for item in PREREQUISITES]}}
    columns = [("schema_migrations", "migration_id", "varchar(255)", "NO", None, "PRI", ""), ("schema_migrations", "applied_at", "datetime", "NO", "CURRENT_TIMESTAMP", "", ""), ("vehiculos", "id_vehiculo", "int", "NO", None, "PRI", "auto_increment"), ("vehiculos", "dia_vencimiento", "tinyint unsigned", "NO", "1", "", ""), ("vehiculos", "telefono", "varchar(30)", "YES", None, "", ""), ("cierres_diarios", "id_cierre", "int", "NO", None, "PRI", ""), ("cierres_diarios", "total_mensualidades", "int", "NO", "0", "", ""), ("cierres_diarios", "total_mensualidades_monto", "int", "NO", "0", "", "")]
    columns = [item for item in columns if item[1] not in missing]
    monthly = [("id_pago_mensual", "int", "NO", None, "PRI", "auto_increment"), ("id_vehiculo", "int", "NO", None, "", ""), ("periodo", "date", "NO", None, "", ""), ("dia_vencimiento_snapshot", "tinyint unsigned", "NO", None, "", ""), ("monto_snapshot", "int", "NO", None, "", ""), ("fecha_pago", "datetime", "NO", None, "", ""), ("usuario", "varchar(50)", "NO", None, "", ""), ("metodo_pago", "varchar(50)", "YES", None, "", ""), ("observacion", "varchar(500)", "YES", None, "", ""), ("id_cierre", "int", "YES", None, "", ""), ("created_at", "datetime", "NO", "CURRENT_TIMESTAMP", "", "")]
    if "pagos_mensuales" in tables:
        columns.extend(("pagos_mensuales", *item) for item in monthly if item[0] not in missing)
    for table, name, kind, nullable, default, key, extra in columns:
        inventory["columns"].append({"table_name": table, "column_name": name, "data_type": kind.split("(", 1)[0].split(" ", 1)[0], "column_type": kind, "is_nullable": nullable, "column_default": default, "column_key": key, "extra": extra})
    for table, name, cols, unique in (("schema_migrations", "PRIMARY", ("migration_id",), True), ("vehiculos", "PRIMARY", ("id_vehiculo",), True), ("cierres_diarios", "PRIMARY", ("id_cierre",), True), ("pagos_mensuales", "PRIMARY", ("id_pago_mensual",), True), ("pagos_mensuales", "uq_pagos_mensuales_vehiculo_periodo", ("id_vehiculo", "periodo"), True), ("pagos_mensuales", "idx_pagos_mensuales_pendiente_cierre", ("id_cierre", "fecha_pago"), False), ("pagos_mensuales", "idx_pagos_mensuales_periodo", ("periodo",), False)):
        if table in tables and name not in missing:
            inventory["indexes"].extend({"table_name": table, "index_name": name, "column_name": column, "seq_in_index": position, "non_unique": 0 if unique else 1} for position, column in enumerate(cols, 1))
    if "pagos_mensuales" in tables:
        inventory["foreign_keys"] = [{"constraint_name": f"fk_pagos_mensuales_{suffix}", "table_name": "pagos_mensuales", "column_name": child, "referenced_table_name": parent, "referenced_column_name": parent_column, "update_rule": "RESTRICT", "delete_rule": "RESTRICT"} for suffix, child, parent, parent_column in (("vehiculo", "id_vehiculo", "vehiculos", "id_vehiculo"), ("cierre", "id_cierre", "cierres_diarios", "id_cierre")) if f"fk_pagos_mensuales_{suffix}" not in missing]
    inventory["pagos_mensuales_duplicates"] = {"available": True, "count": 0}
    inventory["pagos_mensuales_row_count"] = {"available": True, "count": 0}
    inventory["pagos_mensuales_orphans"] = {"vehiculo": {"available": True, "count": 0}, "cierre": {"available": True, "count": 0}}
    return inventory


def _column(inventory, name): return next(row for row in inventory["columns"] if row["column_name"] == name)
def _index(inventory, name): return next(row for row in inventory["indexes"] if row["index_name"] == name)
def _fk(inventory, name): return next(row for row in inventory["foreign_keys"] if row["constraint_name"] == name)
def _table(inventory, name): return next(row for row in inventory["tables"] if row["table_name"] == name)
