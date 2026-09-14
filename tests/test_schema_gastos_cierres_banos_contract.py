import io
import json
import types
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from unittest.mock import patch

from app.db.schema_inventory import gastos_cierres_banos_contract
from app.db.schema_migration_preflight import evaluate_schema_migration_preflight
from app.db.schema_migration_runner import (
    MANAGED_MIGRATION_IDS, MIGRATION_013_ID,
    apply_013_manage_gastos_cierres_banos_contract, main, plan_schema_migrations,
)


PREREQUISITES = list(MANAGED_MIGRATION_IDS[:12])


class Connection:
    def __init__(self): self.statements = []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, statement, params=None): self.statements.append((str(statement), params))


class Engine:
    def __init__(self, connection): self.connection = connection
    def begin(self): return self.connection


class GastosCierresBanosContractTests(unittest.TestCase):
    def test_missing_children_and_totals_plan_safe_additive_creation(self):
        inventory = _inventory(missing=("gastos_operacion", "usos_bano", "total_gastos", "total_neto"))
        migration = _migration(inventory)
        sql = "\n".join(migration["sql"])
        self.assertEqual(migration["status"], "pending")
        self.assertIn("CREATE TABLE gastos_operacion", sql)
        self.assertIn("CREATE TABLE usos_bano", sql)
        self.assertIn("ADD COLUMN total_gastos INT NOT NULL DEFAULT 0", sql)
        self.assertNotRegex(sql, r"(?i)DROP|UPDATE|DELETE|TRUNCATE|operaciones_servicio")

    def test_categoria_widens_50_accepts_80_and_rejects_other_shapes(self):
        inventory = _inventory()
        _column(inventory, "gastos_operacion", "categoria")["column_type"] = "varchar(50)"
        migration = _migration(inventory)
        self.assertEqual(migration["status"], "pending")
        self.assertIn("MODIFY COLUMN categoria VARCHAR(80) NOT NULL", migration["sql"][0])
        self.assertEqual(_migration(_inventory())["status"], "repair_required")
        for column_type in ("varchar(60)", "int"):
            with self.subTest(column_type=column_type):
                inventory = _inventory()
                _column(inventory, "gastos_operacion", "categoria")["column_type"] = column_type
                self.assertEqual(_migration(inventory)["status"], "invalid_contract")

    def test_cierre_totals_can_be_added_but_incompatible_totals_block(self):
        inventory = _inventory(missing=("total_gastos",))
        self.assertEqual(_migration(inventory)["status"], "pending")
        self.assertIn("ADD COLUMN total_gastos", _migration(inventory)["sql"][0])
        inventory = _inventory()
        _column(inventory, "cierres_diarios", "total_neto").update(column_type="varchar(10)")
        self.assertEqual(_migration(inventory)["status"], "invalid_contract")

    def test_gastos_and_bano_indexes_fks_and_legacy_indexes(self):
        inventory = _inventory(missing=("idx_gastos_operacion_pendiente", "fk_gastos_operacion_cierre", "id_cierre_usos", "idx_usos_bano_pendiente", "fk_usos_bano_cierre"))
        migration = _migration(inventory)
        self.assertEqual(migration["status"], "pending")
        sql = "\n".join(migration["sql"])
        self.assertIn("ADD INDEX idx_gastos_operacion_pendiente", sql)
        self.assertIn("ADD COLUMN id_cierre INT NULL", sql)
        self.assertIn("ADD CONSTRAINT fk_usos_bano_cierre", sql)
        inventory = _inventory()
        inventory["indexes"].extend([
            _index_row("gastos_operacion", "idx_gastos_operacion_cierre", ("id_cierre",)),
            _index_row("gastos_operacion", "idx_gastos_operacion_fecha", ("fecha_hora",)),
            _index_row("usos_bano", "idx_usos_bano_cierre", ("id_cierre",)),
        ])
        self.assertTrue(gastos_cierres_banos_contract(inventory)["valid"])
        _fk(inventory, "fk_usos_bano_cierre")["delete_rule"] = "CASCADE"
        self.assertEqual(_migration(inventory)["status"], "invalid_contract")
        inventory = _inventory()
        inventory["foreign_keys"].append({"constraint_name": "fk_gastos_usuario", "table_name": "gastos_operacion", "column_name": "usuario", "referenced_table_name": "usuarios", "referenced_column_name": "usuario", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"})
        self.assertEqual(_migration(inventory)["status"], "invalid_contract")

    def test_orphans_block_before_sql_and_recorded_invalid_state_is_inconsistent(self):
        for table in ("gastos_operacion", "usos_bano"):
            for snapshot in ({"available": True, "count": 1}, {"available": False, "count": None}):
                with self.subTest(table=table, snapshot=snapshot):
                    inventory = _inventory()
                    inventory["gastos_cierres_orphans"][table] = snapshot
                    self.assertEqual(_migration(inventory)["status"], "blocked_prerequisite")
                    self.assertEqual(_migration(inventory)["sql"], [])
                    plan = plan_schema_migrations(inventory)
                    preflight = evaluate_schema_migration_preflight(inventory, plan)
                    self.assertEqual(preflight["status"], "BLOCKED")
                    self.assertIn(f"{table}.id_cierre", preflight["orphan_blockers"])
                    self.assertEqual(
                        next(check["status"] for check in preflight["checks"] if check["name"] == "gastos_cierres_banos_contract"),
                        "BLOCKED",
                    )
        inventory = _inventory(recorded=True)
        _index(inventory, "idx_gastos_operacion_pendiente")["column_name"] = "fecha_hora"
        self.assertEqual(_migration(inventory)["status"], "inconsistent_state")

    def test_missing_children_with_global_fk_name_collision_block_before_sql(self):
        for table, constraint in (
            ("gastos_operacion", "fk_gastos_operacion_cierre"),
            ("usos_bano", "fk_usos_bano_cierre"),
        ):
            with self.subTest(table=table):
                inventory = _inventory(missing=(table,))
                inventory["foreign_keys"].append({
                    "constraint_name": constraint,
                    "table_name": "other_table",
                    "column_name": "other_column",
                    "referenced_table_name": "cierres_diarios",
                    "referenced_column_name": "id_cierre",
                    "update_rule": "RESTRICT",
                    "delete_rule": "RESTRICT",
                })

                migration = _migration(inventory)

                self.assertEqual(migration["status"], "invalid_contract")
                self.assertEqual(migration["sql"], [])
                self.assertIn(
                    f"{constraint} name is already used by a different foreign key",
                    gastos_cierres_banos_contract(inventory)["issues"],
                )

    def test_repair_applied_prerequisite_and_hash_states(self):
        self.assertEqual(_migration(_inventory())["status"], "repair_required")
        self.assertEqual(_migration(_inventory(recorded=True))["status"], "applied")
        blocked = _inventory()
        blocked["migration_snapshot"]["records"] = []
        self.assertEqual(_migration(blocked)["status"], "blocked_prerequisite")
        baseline = evaluate_schema_migration_preflight(_inventory(missing=("idx_usos_bano_pendiente",)), plan_schema_migrations(_inventory(missing=("idx_usos_bano_pendiente",))), {"profile": "installer-production", "environment": "production", "expected_database": "parking"})
        changed = deepcopy(_inventory(missing=("idx_usos_bano_pendiente",)))
        changed["gastos_cierres_orphans"]["gastos_operacion"]["count"] = 1
        altered = evaluate_schema_migration_preflight(changed, plan_schema_migrations(changed), {"profile": "installer-production", "environment": "production", "expected_database": "parking"})
        self.assertNotEqual(baseline["canonical_sha256"], altered["canonical_sha256"])

    def test_apply_registers_after_ddl_and_cli_dispatches(self):
        inventory = _inventory(missing=("total_gastos",))
        connection = Connection()
        with patch("app.db.schema_migration_runner.collect_read_only_schema_inventory_from_engine", return_value=inventory), patch("app.db.schema_migration_preflight.evaluate_schema_migration_preflight", return_value={"checks": []}):
            result = apply_013_manage_gastos_cierres_banos_contract(Engine(connection), backup_confirmed=True, dev_database_confirmed=True, expected_database="parking")
        self.assertEqual(result["status"], "applied")
        self.assertIn("ALTER TABLE cierres_diarios", connection.statements[0][0])
        self.assertEqual(connection.statements[-1][1], {"migration_id": MIGRATION_013_ID})
        output = io.StringIO()
        fake_database = types.SimpleNamespace(engine=Engine(connection))
        with patch.dict("sys.modules", {"app.db.database": fake_database}), patch("app.db.schema_migration_runner.apply_013_manage_gastos_cierres_banos_contract", return_value={"status": "noop"}) as apply, redirect_stdout(output):
            self.assertEqual(main(["--apply-013-manage-gastos-cierres-banos-contract", "--backup-confirmed", "--confirm-dev-db", "--expected-database", "parking"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"status": "noop"})
        apply.assert_called_once()


def _migration(inventory):
    return next(item for item in plan_schema_migrations(inventory)["migrations"] if item["id"] == MIGRATION_013_ID)


def _inventory(missing=(), recorded=False):
    tables = ["schema_migrations", "cierres_diarios"] + [name for name in ("gastos_operacion", "usos_bano") if name not in missing]
    migration_ids = [*PREREQUISITES, *([MIGRATION_013_ID] if recorded else [])]
    inventory = {"database": "parking", "tables": [{"table_name": name, "engine": "InnoDB"} for name in tables], "columns": [], "indexes": [], "foreign_keys": [], "migration_snapshot": {"available": True, "records": [{"migration_id": item} for item in migration_ids]}, "gastos_cierres_orphans": {"gastos_operacion": {"available": True, "count": 0}, "usos_bano": {"available": True, "count": 0}}}
    specs = [("schema_migrations", "migration_id", "varchar(255)", "NO", None, "PRI", ""), ("schema_migrations", "applied_at", "datetime", "NO", "CURRENT_TIMESTAMP", "", ""), ("cierres_diarios", "id_cierre", "int", "NO", None, "PRI", ""), ("cierres_diarios", "total_gastos", "int", "NO", "0", "", ""), ("cierres_diarios", "total_neto", "int", "NO", "0", "", "")]
    specs += [("gastos_operacion", name, kind, nullable, default, key, extra) for name, kind, nullable, default, key, extra in [("id_gasto", "int", "NO", None, "PRI", "auto_increment"), ("fecha_hora", "datetime", "NO", None, "", ""), ("categoria", "varchar(80)", "NO", None, "", ""), ("descripcion", "varchar(500)", "NO", None, "", ""), ("monto", "int", "NO", None, "", ""), ("usuario", "varchar(50)", "NO", None, "", ""), ("id_cierre", "int", "YES", None, "", ""), ("created_at", "datetime", "NO", "CURRENT_TIMESTAMP", "", "")] if "gastos_operacion" in tables]
    specs += [("usos_bano", name, kind, nullable, default, key, extra) for name, kind, nullable, default, key, extra in [("id", "int", "NO", None, "PRI", "auto_increment"), ("fecha_hora", "datetime", "NO", None, "", ""), ("monto", "int", "NO", None, "", ""), ("usuario", "varchar(50)", "NO", None, "", ""), ("id_cierre", "int", "YES", None, "", "")] if "usos_bano" in tables]
    for table, name, kind, nullable, default, key, extra in specs:
        if name not in missing and not (table == "usos_bano" and name == "id_cierre" and "id_cierre_usos" in missing):
            inventory["columns"].append({"table_name": table, "column_name": name, "data_type": kind.split("(", 1)[0], "column_type": kind, "is_nullable": nullable, "column_default": default, "column_key": key, "extra": extra})
    for table, name, columns in (("schema_migrations", "PRIMARY", ("migration_id",)), ("cierres_diarios", "PRIMARY", ("id_cierre",)), ("gastos_operacion", "PRIMARY", ("id_gasto",)), ("gastos_operacion", "idx_gastos_operacion_pendiente", ("id_cierre", "fecha_hora")), ("usos_bano", "PRIMARY", ("id",)), ("usos_bano", "idx_usos_bano_pendiente", ("id_cierre", "fecha_hora"))):
        if table in tables and name not in missing:
            inventory["indexes"].extend(_index_row(table, name, columns))
    for table, name in (("gastos_operacion", "fk_gastos_operacion_cierre"), ("usos_bano", "fk_usos_bano_cierre")):
        if table in tables and name not in missing:
            inventory["foreign_keys"].append({"constraint_name": name, "table_name": table, "column_name": "id_cierre", "referenced_table_name": "cierres_diarios", "referenced_column_name": "id_cierre", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"})
    return inventory


def _index_row(table, name, columns): return [{"table_name": table, "index_name": name, "column_name": column, "seq_in_index": position, "non_unique": 0 if name == "PRIMARY" else 1} for position, column in enumerate(columns, 1)]
def _column(inventory, table, name): return next(row for row in inventory["columns"] if row["table_name"] == table and row["column_name"] == name)
def _index(inventory, name): return next(row for row in inventory["indexes"] if row["index_name"] == name)
def _fk(inventory, name): return next(row for row in inventory["foreign_keys"] if row["constraint_name"] == name)
