import re
import unittest
from copy import deepcopy

from app.db.schema_inventory import (
    collect_read_only_schema_inventory,
    pagos_mensuales_metodo_pago_contract,
    operaciones_servicio_ingreso_generado_fk_contract,
    operaciones_servicio_tipo_vehiculo_lavado_fk_contract,
    operaciones_servicio_contract,
    tipos_lavado_contract,
)
from app.db.schema_migration_runner import _wash_pricing_issues, plan_schema_migrations
from app.db.schema_migration_preflight import evaluate_schema_migration_preflight


class FakeResult:
    def __init__(self, rows=None, scalar_value=None, uppercase_row_keys=False):
        self.rows = [
            {key.upper() if uppercase_row_keys else key: value for key, value in row.items()}
            for row in rows or []
        ]
        self.scalar_value = scalar_value

    def scalar(self):
        return self.scalar_value

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeConnection:
    def __init__(
        self, *, include_config=True, include_schema_migrations=False,
        migration_records=None, include_tipos_lavado=False, tipos_lavado_records=None,
        schema_name="parking", uppercase_row_keys=False, include_operaciones_fk_prerequisites=False,
        include_tipo_vehiculo_lavado_fk_prerequisites=False, orphan_count=0,
        config_records=None,
    ):
        self.include_config = include_config
        self.include_schema_migrations = include_schema_migrations
        self.migration_records = migration_records or []
        self.include_tipos_lavado = include_tipos_lavado
        self.tipos_lavado_records = tipos_lavado_records or []
        self.schema_name = schema_name
        self.uppercase_row_keys = uppercase_row_keys
        self.include_operaciones_fk_prerequisites = include_operaciones_fk_prerequisites
        self.include_tipo_vehiculo_lavado_fk_prerequisites = include_tipo_vehiculo_lavado_fk_prerequisites
        self.orphan_count = orphan_count
        self.config_records = config_records or [
            {"clave": "tarifa_minima", "valor": "300"},
            {"clave": "modo_cobro", "valor": "hora"},
        ]
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if "DATABASE()" in sql:
            return FakeResult(scalar_value=self.schema_name)
        if "information_schema.tables" in sql:
            rows = [
                {"table_name": "vehiculos", "table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4"},
            ]
            if self.include_config:
                rows.append({"table_name": "configuracion", "table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4"})
            if self.include_schema_migrations:
                rows.append({"table_name": "schema_migrations", "table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4"})
            if self.include_tipos_lavado:
                rows.append({"table_name": "tipos_lavado", "table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4"})
            if self.include_operaciones_fk_prerequisites:
                rows.extend([
                    {"table_name": "operaciones_servicio", "table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4"},
                    {"table_name": "ingresos", "table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4"},
                ])
            if self.include_tipo_vehiculo_lavado_fk_prerequisites:
                rows.append({"table_name": "tipos_vehiculo_lavado", "table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4"})
                if not self.include_operaciones_fk_prerequisites:
                    rows.append({"table_name": "operaciones_servicio", "table_type": "BASE TABLE", "engine": "InnoDB", "table_collation": "utf8mb4"})
            return FakeResult(rows, uppercase_row_keys=self.uppercase_row_keys)
        if "information_schema.columns" in sql:
            rows = [
                {"table_name": "vehiculos", "column_name": "patente", "ordinal_position": 2, "column_default": None, "is_nullable": "NO", "data_type": "varchar", "column_type": "varchar(10)", "column_key": "", "extra": "", "character_set_name": "utf8mb4", "collation_name": "utf8mb4"},
                {"table_name": "vehiculos", "column_name": "id_vehiculo", "ordinal_position": 1, "column_default": None, "is_nullable": "NO", "data_type": "int", "column_type": "int", "column_key": "PRI", "extra": "auto_increment"},
            ]
            if self.include_schema_migrations:
                rows.extend([
                    {"table_name": "schema_migrations", "column_name": "migration_id", "ordinal_position": 1, "column_default": None, "is_nullable": "NO", "data_type": "varchar", "column_type": "varchar(255)", "column_key": "PRI", "extra": ""},
                    {"table_name": "schema_migrations", "column_name": "applied_at", "ordinal_position": 2, "column_default": "CURRENT_TIMESTAMP", "is_nullable": "NO", "data_type": "datetime", "column_type": "datetime", "column_key": "", "extra": ""},
                ])
            if self.include_tipos_lavado:
                rows.extend([
                    {"table_name": "tipos_lavado", "column_name": "id_tipo_lavado", "ordinal_position": 1, "column_default": None, "is_nullable": "NO", "data_type": "int", "column_type": "int", "column_key": "PRI", "extra": "auto_increment"},
                    {"table_name": "tipos_lavado", "column_name": "codigo", "ordinal_position": 2, "column_default": None, "is_nullable": "NO", "data_type": "varchar", "column_type": "varchar(50)", "column_key": "UNI", "extra": ""},
                    {"table_name": "tipos_lavado", "column_name": "nombre", "ordinal_position": 3, "column_default": None, "is_nullable": "NO", "data_type": "varchar", "column_type": "varchar(80)", "column_key": "", "extra": ""},
                    {"table_name": "tipos_lavado", "column_name": "activo", "ordinal_position": 4, "column_default": "1", "is_nullable": "NO", "data_type": "tinyint", "column_type": "tinyint(1)", "column_key": "", "extra": ""},
                    {"table_name": "tipos_lavado", "column_name": "created_at", "ordinal_position": 5, "column_default": "CURRENT_TIMESTAMP", "is_nullable": "NO", "data_type": "datetime", "column_type": "datetime", "column_key": "", "extra": ""},
                    {"table_name": "tipos_lavado", "column_name": "updated_at", "ordinal_position": 6, "column_default": "CURRENT_TIMESTAMP", "is_nullable": "NO", "data_type": "datetime", "column_type": "datetime", "column_key": "", "extra": "on update CURRENT_TIMESTAMP"},
                ])
            if self.include_operaciones_fk_prerequisites:
                rows.extend([
                    {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "ordinal_position": 1, "column_default": None, "is_nullable": "YES", "data_type": "int", "column_type": "int", "column_key": "", "extra": ""},
                    {"table_name": "ingresos", "column_name": "id_ingreso", "ordinal_position": 1, "column_default": None, "is_nullable": "NO", "data_type": "int", "column_type": "int", "column_key": "PRI", "extra": ""},
                ])
            if self.include_tipo_vehiculo_lavado_fk_prerequisites:
                rows.extend([
                    {"table_name": "operaciones_servicio", "column_name": "id_tipo_vehiculo_lavado", "ordinal_position": 2, "column_default": None, "is_nullable": "YES", "data_type": "int", "column_type": "int", "column_key": "", "extra": ""},
                    {"table_name": "tipos_vehiculo_lavado", "column_name": "id_tipo_vehiculo_lavado", "ordinal_position": 1, "column_default": None, "is_nullable": "NO", "data_type": "int", "column_type": "int", "column_key": "PRI", "extra": ""},
                ])
            return FakeResult(rows, uppercase_row_keys=self.uppercase_row_keys)
        if "information_schema.statistics" in sql:
            rows = [
                {"table_name": "vehiculos", "index_name": "idx_patente", "non_unique": 1, "seq_in_index": 1, "column_name": "patente", "collation": "A", "index_type": "BTREE"},
                {"table_name": "vehiculos", "index_name": "PRIMARY", "non_unique": 0, "seq_in_index": 1, "column_name": "id_vehiculo", "collation": "A", "index_type": "BTREE"},
            ]
            if self.include_schema_migrations:
                rows.append({"table_name": "schema_migrations", "index_name": "PRIMARY", "non_unique": 0, "seq_in_index": 1, "column_name": "migration_id", "collation": "A", "index_type": "BTREE"})
            if self.include_tipos_lavado:
                rows.extend([
                    {"table_name": "tipos_lavado", "index_name": "PRIMARY", "non_unique": 0, "seq_in_index": 1, "column_name": "id_tipo_lavado", "collation": "A", "index_type": "BTREE"},
                    {"table_name": "tipos_lavado", "index_name": "codigo", "non_unique": 0, "seq_in_index": 1, "column_name": "codigo", "collation": "A", "index_type": "BTREE"},
                ])
            if self.include_operaciones_fk_prerequisites:
                rows.extend([
                    {"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_ingreso_generado", "non_unique": 1, "seq_in_index": 1, "column_name": "id_ingreso_generado", "collation": "A", "index_type": "BTREE"},
                    {"table_name": "ingresos", "index_name": "PRIMARY", "non_unique": 0, "seq_in_index": 1, "column_name": "id_ingreso", "collation": "A", "index_type": "BTREE"},
                ])
            if self.include_tipo_vehiculo_lavado_fk_prerequisites:
                rows.append({"table_name": "tipos_vehiculo_lavado", "index_name": "PRIMARY", "non_unique": 0, "seq_in_index": 1, "column_name": "id_tipo_vehiculo_lavado", "collation": "A", "index_type": "BTREE"})
            return FakeResult(rows, uppercase_row_keys=self.uppercase_row_keys)
        if "information_schema.referential_constraints" in sql:
            return FakeResult([
                {"constraint_name": "fk_vehicle_owner", "table_name": "vehiculos", "column_name": "owner_id", "ordinal_position": 1, "referenced_table_name": "usuarios", "referenced_column_name": "id_usuario", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"},
            ], uppercase_row_keys=self.uppercase_row_keys)
        if "FROM configuracion" in sql:
            return FakeResult(
                self.config_records,
                uppercase_row_keys=self.uppercase_row_keys,
            )
        if "FROM schema_migrations" in sql:
            return FakeResult(self.migration_records, uppercase_row_keys=self.uppercase_row_keys)
        if "FROM tipos_lavado" in sql:
            return FakeResult(self.tipos_lavado_records, uppercase_row_keys=self.uppercase_row_keys)
        if "FROM operaciones_servicio AS child" in sql:
            return FakeResult(scalar_value=self.orphan_count)
        raise AssertionError(f"Unexpected query: {sql}")


class SchemaInventoryTests(unittest.TestCase):
    def test_collects_sorted_read_only_inventory(self):
        conn = FakeConnection()

        inventory = collect_read_only_schema_inventory(conn)

        self.assertEqual(inventory["inventory_version"], 1)
        self.assertEqual(inventory["database"], "parking")
        self.assertEqual([row["table_name"] for row in inventory["tables"]], ["configuracion", "vehiculos"])
        self.assertEqual([row["column_name"] for row in inventory["columns"]], ["id_vehiculo", "patente"])
        columns_query = next(statement for statement, _ in conn.statements if "information_schema.columns" in statement)
        self.assertIn("character_set_name", columns_query)
        self.assertIn("collation_name", columns_query)
        self.assertEqual([row["index_name"] for row in inventory["indexes"]], ["PRIMARY", "idx_patente"])
        self.assertEqual(inventory["foreign_keys"][0]["constraint_name"], "fk_vehicle_owner")
        self.assertEqual(inventory["config_seed_snapshot"], {
            "source_table": "configuracion",
            "available": True,
            "values": [{"clave": "modo_cobro", "valor": "hora"}, {"clave": "tarifa_minima", "valor": "300"}],
        })
        self.assertEqual(inventory["migration_snapshot"], {
            "source_table": "schema_migrations",
            "available": False,
            "contract": {"valid": None, "issues": []},
            "records": [],
        })
        self.assertEqual(inventory["tipos_lavado_seed_snapshot"], {
            "source_table": "tipos_lavado", "available": False,
            "contract": {"valid": None, "issues": []}, "records": [],
        })
        self.assertFalse(any("FROM schema_migrations" in statement for statement, _ in conn.statements))

        forbidden = ("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE", "REPLACE", "TRUNCATE")
        for statement, _ in conn.statements:
            normalized = statement.upper()
            self.assertTrue(normalized.lstrip().startswith("SELECT"))
            self.assertFalse(any(re.search(rf"\b{keyword}\b", normalized) for keyword in forbidden))

    def test_skips_config_snapshot_when_configuracion_table_is_absent(self):
        conn = FakeConnection(include_config=False)

        inventory = collect_read_only_schema_inventory(conn)

        self.assertEqual(inventory["config_seed_snapshot"], {
            "source_table": "configuracion",
            "available": False,
            "values": [],
        })
        self.assertFalse(any("FROM configuracion" in statement for statement, _ in conn.statements))

    def test_collects_wash_price_variants_for_007_without_capturing_unrelated_config(self):
        conn = FakeConnection(config_records=[
            {"clave": "lavado_citycar", "valor": "5000"},
            {"clave": " LAVADO_CITYCAR ", "valor": "6000"},
            {"clave": "lavado_api_token", "valor": "sensitive"},
            {"clave": "api_token", "valor": "sensitive"},
        ])

        inventory = collect_read_only_schema_inventory(conn)
        values = inventory["config_seed_snapshot"]["values"]
        plan = plan_schema_migrations(inventory)

        self.assertEqual(values, [
            {"clave": " LAVADO_CITYCAR ", "valor": "6000"},
            {"clave": "lavado_citycar", "valor": "5000"},
        ])
        self.assertIn("configuracion has duplicate or ambiguous wash pricing codes", _wash_pricing_issues(inventory))
        self.assertEqual(
            plan["wash_vehicle_type_pricing"]["source_data"]["configuracion"]["values"],
            values,
        )
        without_variant = deepcopy(inventory)
        without_variant["config_seed_snapshot"]["values"] = values[1:]
        self.assertNotEqual(
            evaluate_schema_migration_preflight(inventory, plan)["canonical_sha256"],
            evaluate_schema_migration_preflight(
                without_variant, plan_schema_migrations(without_variant)
            )["canonical_sha256"],
        )
        config_query, params = next(
            (statement, params) for statement, params in conn.statements if "FROM configuracion" in statement
        )
        self.assertIn("LOWER(TRIM(clave)) LIKE", config_query)
        self.assertEqual(params["wash_key_prefix"], "lavado%")

    def test_collects_migration_snapshot_only_when_tracking_table_exists(self):
        conn = FakeConnection(
            include_schema_migrations=True,
            migration_records=[
                {"migration_id": "002", "applied_at": "2026-01-02T00:00:00"},
                {"migration_id": "001", "applied_at": "2026-01-01T00:00:00"},
            ],
        )

        inventory = collect_read_only_schema_inventory(conn)

        self.assertEqual(inventory["migration_snapshot"], {
            "source_table": "schema_migrations",
            "available": True,
            "contract": {"valid": True, "issues": []},
            "records": [
                {"migration_id": "001", "applied_at": "2026-01-01T00:00:00"},
                {"migration_id": "002", "applied_at": "2026-01-02T00:00:00"},
            ],
        })
        migration_queries = [statement for statement, _ in conn.statements if "FROM schema_migrations" in statement]
        self.assertEqual(len(migration_queries), 1)
        self.assertRegex(migration_queries[0], r"SELECT\s+migration_id, applied_at")
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement, _ in conn.statements))

    def test_normalizes_uppercase_pymysql_mapping_keys(self):
        inventory = collect_read_only_schema_inventory(FakeConnection(uppercase_row_keys=True))

        self.assertEqual(inventory["tables"][0]["table_name"], "configuracion")
        self.assertEqual(inventory["columns"][0]["column_name"], "id_vehiculo")
        self.assertEqual(inventory["indexes"][0]["index_name"], "PRIMARY")
        self.assertEqual(inventory["foreign_keys"][0]["constraint_name"], "fk_vehicle_owner")
        self.assertEqual(inventory["config_seed_snapshot"]["values"][0], {"clave": "modo_cobro", "valor": "hora"})

    def test_collects_tipos_lavado_seed_snapshot_only_for_valid_table(self):
        conn = FakeConnection(
            include_tipos_lavado=True,
            tipos_lavado_records=[{"codigo": "lavado_general", "nombre": "Custom", "activo": 0}],
        )
        inventory = collect_read_only_schema_inventory(conn)

        self.assertEqual(inventory["tipos_lavado_seed_snapshot"]["records"], [
            {"codigo": "lavado_general", "nombre": "Custom", "activo": 0},
        ])
        self.assertTrue(inventory["tipos_lavado_seed_snapshot"]["contract"]["valid"])
        self.assertTrue(any("FROM tipos_lavado" in statement for statement, _ in conn.statements))

    def test_rejects_composite_unique_index_for_codigo(self):
        inventory = collect_read_only_schema_inventory(FakeConnection(include_tipos_lavado=True))
        inventory["indexes"] = [
            index for index in inventory["indexes"]
            if index["table_name"] != "tipos_lavado"
        ] + [
            {"table_name": "tipos_lavado", "index_name": "codigo_otra_columna", "non_unique": 0, "seq_in_index": 1, "column_name": "codigo"},
            {"table_name": "tipos_lavado", "index_name": "codigo_otra_columna", "non_unique": 0, "seq_in_index": 2, "column_name": "otra_columna"},
        ]

        contract = tipos_lavado_contract(inventory)

        self.assertFalse(contract["valid"])
        self.assertIn("codigo must be UNIQUE", contract["issues"])

    def test_requires_active_database_name(self):
        conn = FakeConnection(schema_name=None)

        with self.assertRaisesRegex(RuntimeError, "active database name"):
            collect_read_only_schema_inventory(conn)

    def test_fk_contract_requires_safe_prerequisites_and_zero_orphans(self):
        inventory = {
            "tables": [{"table_name": "operaciones_servicio", "engine": "InnoDB"}, {"table_name": "ingresos", "engine": "InnoDB"}],
            "columns": [
                {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "data_type": "int", "column_type": "int", "is_nullable": "YES"},
                {"table_name": "ingresos", "column_name": "id_ingreso", "data_type": "int", "column_type": "int", "is_nullable": "NO"},
            ],
            "indexes": [
                {"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_ingreso_generado", "column_name": "id_ingreso_generado", "seq_in_index": 1},
                {"table_name": "ingresos", "index_name": "PRIMARY", "column_name": "id_ingreso", "seq_in_index": 1},
            ],
            "foreign_keys": [],
            "operaciones_servicio_ingreso_generado_orphans": {"available": True, "count": 0},
        }
        self.assertEqual(operaciones_servicio_ingreso_generado_fk_contract(inventory)["state"], "safe_to_add")
        inventory["operaciones_servicio_ingreso_generado_orphans"]["count"] = 1
        self.assertEqual(operaciones_servicio_ingreso_generado_fk_contract(inventory)["state"], "blocked_orphans")
        inventory["indexes"] = inventory["indexes"][1:]
        contract = operaciones_servicio_ingreso_generado_fk_contract(inventory)
        self.assertEqual(contract["state"], "invalid")
        self.assertIn("idx_operaciones_servicio_ingreso_generado index is missing", contract["issues"])

    def test_wash_vehicle_type_fk_contract_allows_absent_child_index_only_while_pending(self):
        inventory = {
            "tables": [
                {"table_name": "operaciones_servicio", "engine": "InnoDB"},
                {"table_name": "tipos_vehiculo_lavado", "engine": "InnoDB"},
            ],
            "columns": [
                {"table_name": "operaciones_servicio", "column_name": "id_tipo_vehiculo_lavado", "data_type": "int", "column_type": "int", "is_nullable": "YES"},
                {"table_name": "tipos_vehiculo_lavado", "column_name": "id_tipo_vehiculo_lavado", "data_type": "int", "column_type": "int", "is_nullable": "NO"},
            ],
            "indexes": [{"table_name": "tipos_vehiculo_lavado", "index_name": "PRIMARY", "column_name": "id_tipo_vehiculo_lavado", "seq_in_index": 1}],
            "foreign_keys": [],
            "operaciones_servicio_tipo_vehiculo_lavado_orphans": {"available": True, "count": 0},
        }
        self.assertEqual(operaciones_servicio_tipo_vehiculo_lavado_fk_contract(inventory)["state"], "safe_to_add")
        inventory["indexes"].append({"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_tipo_vehiculo_lavado", "column_name": "other_id", "seq_in_index": 1})
        contract = operaciones_servicio_tipo_vehiculo_lavado_fk_contract(inventory)
        self.assertEqual(contract["state"], "invalid")
        self.assertFalse(contract["add_safe"])

    def test_fk_contract_accepts_restrictive_no_action_or_restrict_rules(self):
        inventory = {
            "tables": [{"table_name": "operaciones_servicio", "engine": "InnoDB"}, {"table_name": "ingresos", "engine": "InnoDB"}],
            "columns": [
                {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "data_type": "int", "column_type": "int", "is_nullable": "YES"},
                {"table_name": "ingresos", "column_name": "id_ingreso", "data_type": "int", "column_type": "int", "is_nullable": "NO"},
            ],
            "indexes": [
                {"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_ingreso_generado", "column_name": "id_ingreso_generado", "seq_in_index": 1},
                {"table_name": "ingresos", "index_name": "PRIMARY", "column_name": "id_ingreso", "seq_in_index": 1},
            ],
            "operaciones_servicio_ingreso_generado_orphans": {"available": True, "count": 0},
        }
        for update_rule, delete_rule in (("NO ACTION", "NO ACTION"), ("RESTRICT", "RESTRICT")):
            with self.subTest(update_rule=update_rule, delete_rule=delete_rule):
                contract = operaciones_servicio_ingreso_generado_fk_contract({
                    **inventory,
                    "foreign_keys": [{
                        "constraint_name": "fk_operaciones_servicio_ingreso_generado",
                        "table_name": "operaciones_servicio",
                        "column_name": "id_ingreso_generado",
                        "referenced_table_name": "ingresos",
                        "referenced_column_name": "id_ingreso",
                        "update_rule": update_rule,
                        "delete_rule": delete_rule,
                    }],
                })
                self.assertEqual((contract["valid"], contract["state"]), (True, "valid"))

    def test_fk_contract_rejects_non_restrictive_rules(self):
        inventory = {
            "tables": [{"table_name": "operaciones_servicio", "engine": "InnoDB"}, {"table_name": "ingresos", "engine": "InnoDB"}],
            "columns": [
                {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "data_type": "int", "column_type": "int", "is_nullable": "YES"},
                {"table_name": "ingresos", "column_name": "id_ingreso", "data_type": "int", "column_type": "int", "is_nullable": "NO"},
            ],
            "indexes": [
                {"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_ingreso_generado", "column_name": "id_ingreso_generado", "seq_in_index": 1},
                {"table_name": "ingresos", "index_name": "PRIMARY", "column_name": "id_ingreso", "seq_in_index": 1},
            ],
            "operaciones_servicio_ingreso_generado_orphans": {"available": True, "count": 0},
        }
        for rule in ("CASCADE", "SET NULL", "SET DEFAULT"):
            with self.subTest(rule=rule):
                contract = operaciones_servicio_ingreso_generado_fk_contract({
                    **inventory,
                    "foreign_keys": [{
                        "constraint_name": "fk_operaciones_servicio_ingreso_generado",
                        "table_name": "operaciones_servicio",
                        "column_name": "id_ingreso_generado",
                        "referenced_table_name": "ingresos",
                        "referenced_column_name": "id_ingreso",
                        "update_rule": rule,
                        "delete_rule": "RESTRICT",
                    }],
                })
                self.assertFalse(contract["valid"])
                self.assertEqual(contract["state"], "name_collision")

    def test_fk_contract_requires_compatible_ints_innodb_and_unique_constraint_name(self):
        base = {
            "tables": [{"table_name": "operaciones_servicio", "engine": "InnoDB"}, {"table_name": "ingresos", "engine": "InnoDB"}],
            "columns": [
                {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "data_type": "int", "column_type": "int(11)", "is_nullable": "YES"},
                {"table_name": "ingresos", "column_name": "id_ingreso", "data_type": "int", "column_type": "int", "is_nullable": "NO"},
            ],
            "indexes": [
                {"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_ingreso_generado", "column_name": "id_ingreso_generado", "seq_in_index": 1},
                {"table_name": "ingresos", "index_name": "PRIMARY", "column_name": "id_ingreso", "seq_in_index": 1},
            ],
            "foreign_keys": [],
            "operaciones_servicio_ingreso_generado_orphans": {"available": True, "count": 0},
        }
        for mutation, state in (
            (lambda value: value["columns"][1].update(column_type="int unsigned"), "invalid"),
            (lambda value: value["columns"][0].update(data_type="bigint", column_type="bigint"), "invalid"),
            (lambda value: value["tables"][0].update(engine="MyISAM"), "invalid"),
            (lambda value: value["tables"][1].pop("engine"), "unknown"),
            (lambda value: value.update(foreign_keys=[{"constraint_name": "fk_operaciones_servicio_ingreso_generado", "table_name": "other", "column_name": "other_id", "referenced_table_name": "ingresos", "referenced_column_name": "id_ingreso", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"}]), "name_collision"),
        ):
            with self.subTest(mutation=mutation):
                inventory = {**base, "tables": [dict(row) for row in base["tables"]], "columns": [dict(row) for row in base["columns"]]}
                mutation(inventory)
                contract = operaciones_servicio_ingreso_generado_fk_contract(inventory)
                self.assertEqual(contract["state"], state)
                self.assertFalse(contract["add_safe"])
                self.assertFalse(contract["orphan_check_safe"])

    def test_fk_contract_rejects_unsigned_child_and_parent(self):
        inventory = {
            "tables": [{"table_name": "operaciones_servicio", "engine": "InnoDB"}, {"table_name": "ingresos", "engine": "InnoDB"}],
            "columns": [
                {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "data_type": "int", "column_type": "int unsigned", "is_nullable": "YES"},
                {"table_name": "ingresos", "column_name": "id_ingreso", "data_type": "int", "column_type": "int unsigned", "is_nullable": "NO"},
            ],
            "indexes": [
                {"table_name": "operaciones_servicio", "index_name": "idx_operaciones_servicio_ingreso_generado", "column_name": "id_ingreso_generado", "seq_in_index": 1},
                {"table_name": "ingresos", "index_name": "PRIMARY", "column_name": "id_ingreso", "seq_in_index": 1},
            ],
            "foreign_keys": [],
            "operaciones_servicio_ingreso_generado_orphans": {"available": True, "count": 0},
        }

        contract = operaciones_servicio_ingreso_generado_fk_contract(inventory)

        self.assertFalse(contract["valid"])
        self.assertFalse(contract["add_safe"])
        self.assertEqual(contract["state"], "invalid")
        self.assertIn("id_ingreso_generado must be signed INT NULL", contract["issues"])
        self.assertIn("ingresos.id_ingreso must be signed INT", contract["issues"])

    def test_collects_orphans_only_after_fk_query_prerequisites_exist(self):
        unavailable = FakeConnection()
        collect_read_only_schema_inventory(unavailable)
        self.assertFalse(any("FROM operaciones_servicio AS child" in statement for statement, _ in unavailable.statements))
        available = FakeConnection(include_operaciones_fk_prerequisites=True, orphan_count=2)
        inventory = collect_read_only_schema_inventory(available)
        self.assertEqual(inventory["operaciones_servicio_ingreso_generado_orphans"], {"available": True, "count": 2})
        self.assertTrue(any("FROM operaciones_servicio AS child" in statement for statement, _ in available.statements))

    def test_collects_wash_vehicle_type_orphans_only_after_its_columns_exist(self):
        unavailable = FakeConnection()
        inventory = collect_read_only_schema_inventory(unavailable)
        self.assertEqual(inventory["operaciones_servicio_tipo_vehiculo_lavado_orphans"], {"available": False, "count": None})
        self.assertFalse(any("tipos_vehiculo_lavado AS parent" in statement for statement, _ in unavailable.statements))
        available = FakeConnection(include_tipo_vehiculo_lavado_fk_prerequisites=True, orphan_count=2)
        inventory = collect_read_only_schema_inventory(available)
        self.assertEqual(inventory["operaciones_servicio_tipo_vehiculo_lavado_orphans"], {"available": True, "count": 2})
        self.assertTrue(any("tipos_vehiculo_lavado AS parent" in statement for statement, _ in available.statements))

    def test_classifies_monthly_payment_method_widen_contract(self):
        base = {"tables": [{"table_name": "pagos_mensuales"}]}
        for column, expected in (
            (None, (False, False, "missing_column")),
            ({"data_type": "varchar", "column_type": "varchar(40)", "is_nullable": "YES", "column_default": None, "extra": "", "character_set_name": "utf8mb4", "collation_name": "utf8mb4"}, (False, True, "widen_safe")),
            ({"data_type": "varchar", "column_type": "varchar(50)", "is_nullable": "YES", "column_default": None, "extra": "", "character_set_name": "utf8mb4", "collation_name": "utf8mb4"}, (True, False, "valid")),
            ({"data_type": "varchar", "column_type": "varchar(60)", "is_nullable": "YES", "column_default": None}, (False, False, "invalid")),
            ({"data_type": "int", "column_type": "int", "is_nullable": "YES", "column_default": None}, (False, False, "invalid")),
            ({"data_type": "varchar", "column_type": "varchar(40)", "is_nullable": "NO", "column_default": None}, (False, False, "invalid")),
            ({"data_type": "varchar", "column_type": "varchar(40)", "is_nullable": "YES", "column_default": "cash"}, (False, False, "invalid")),
        ):
            with self.subTest(column=column):
                inventory = {"tables": [{"table_name": "pagos_mensuales", "table_collation": "utf8mb4"}]}
                inventory["columns"] = [] if column is None else [{
                    "table_name": "pagos_mensuales", "column_name": "metodo_pago", **column,
                }]
                contract = pagos_mensuales_metodo_pago_contract(inventory)
                self.assertEqual(
                    (contract["valid"], contract["widen_safe"], contract["state"]), expected
                )

    def test_rejects_monthly_payment_method_widen_with_extra_or_nondefault_collation(self):
        base = {
            "tables": [{"table_name": "pagos_mensuales", "table_collation": "utf8mb4_0900_ai_ci"}],
            "columns": [{
                "table_name": "pagos_mensuales", "column_name": "metodo_pago",
                "data_type": "varchar", "column_type": "varchar(40)", "is_nullable": "YES",
                "column_default": None, "extra": "", "character_set_name": "utf8mb4",
                "collation_name": "utf8mb4_0900_ai_ci",
            }],
        }
        for field, value, issue in (
            ("extra", "INVISIBLE", "metodo_pago extra must be empty"),
            ("collation_name", "utf8mb4_bin", "metodo_pago collation must match the table default"),
            ("character_set_name", "latin1", "metodo_pago character set must match the table default"),
        ):
            with self.subTest(field=field):
                inventory = {**base, "columns": [{**base["columns"][0], field: value}]}
                contract = pagos_mensuales_metodo_pago_contract(inventory)

                self.assertEqual((contract["valid"], contract["widen_safe"], contract["state"]), (False, False, "invalid"))
                self.assertIn(issue, contract["issues"])

    def test_operaciones_servicio_contract_classifies_valid_safe_and_invalid_states(self):
        inventory = _operaciones_servicio_inventory()
        self.assertEqual((operaciones_servicio_contract(inventory)["valid"], operaciones_servicio_contract(inventory)["state"]), (True, "valid"))

        missing = deepcopy(inventory)
        missing["columns"] = [row for row in missing["columns"] if row["column_name"] != "usuario_fin"]
        contract = operaciones_servicio_contract(missing)
        self.assertEqual((contract["valid"], contract["add_safe"], contract["state"]), (False, True, "safe_to_upgrade"))
        self.assertEqual(contract["missing_columns"], ["usuario_fin"])

        for mutation, issue in (
            (lambda value: next(row for row in value["columns"] if row["column_name"] == "duracion_minutos").update(column_type="bigint"), "duracion_minutos column_type must be int"),
            (lambda value: next(row for row in value["columns"] if row["column_name"] == "tipo_vehiculo_lavado_snapshot").update(is_nullable="NO"), "tipo_vehiculo_lavado_snapshot must be NULL"),
            (lambda value: next(row for row in value["columns"] if row["column_name"] == "estado").update(column_default="cerrado"), "estado default must be ACTIVO"),
            (lambda value: next(row for row in value["indexes"] if row["index_name"] == "idx_operaciones_servicio_patente").update(column_name="estado"), "idx_operaciones_servicio_patente name is already used by a different index"),
            (lambda value: next(row for row in value["indexes"] if row["index_name"] == "idx_operaciones_servicio_patente").update(non_unique=0), "idx_operaciones_servicio_patente name is already used by a different index"),
        ):
            with self.subTest(issue=issue):
                invalid = deepcopy(inventory)
                mutation(invalid)
                contract = operaciones_servicio_contract(invalid)
                self.assertEqual(contract["state"], "invalid")
                self.assertIn(issue, contract["issues"])

        for mutation in (
            lambda value: value["foreign_keys"].pop(),
            lambda value: value["foreign_keys"][0].update(referenced_table_name="other"),
        ):
            with self.subTest(mutation=mutation):
                invalid = deepcopy(inventory)
                mutation(invalid)
                self.assertEqual(operaciones_servicio_contract(invalid)["state"], "invalid")

    def test_operaciones_servicio_estado_requires_all_written_enum_values(self):
        for missing_state in ("FINALIZADO_COBRADO", "CONVERTIDO_ESTADIA"):
            with self.subTest(missing_state=missing_state):
                inventory = _operaciones_servicio_inventory()
                estado = next(row for row in inventory["columns"] if row["column_name"] == "estado")
                estado["column_type"] = "enum(" + ",".join(
                    f"'{value}'"
                    for value in ("ACTIVO", "FINALIZADO_COBRADO", "CONVERTIDO_ESTADIA")
                    if value != missing_state
                ) + ")"

                contract = operaciones_servicio_contract(inventory)

                self.assertFalse(contract["valid"])
                self.assertEqual(contract["state"], "invalid")
                self.assertIn("estado ENUM must exactly match application-written states", contract["issues"])

    def test_operaciones_servicio_estado_rejects_lowercase_and_mixed_case_enum_values(self):
        for states in (
            ("activo", "finalizado_cobrado", "convertido_estadia"),
            ("ACTIVO", "Finalizado_Cobrado", "CONVERTIDO_ESTADIA"),
        ):
            with self.subTest(states=states):
                inventory = _operaciones_servicio_inventory()
                estado = next(row for row in inventory["columns"] if row["column_name"] == "estado")
                estado["column_type"] = "enum(" + ",".join(f"'{value}'" for value in states) + ")"

                contract = operaciones_servicio_contract(inventory)

                self.assertFalse(contract["valid"])
                self.assertEqual(contract["state"], "invalid")
                self.assertIn("estado ENUM must exactly match application-written states", contract["issues"])

    def test_operaciones_servicio_estado_rejects_extra_case_variant_enum_values(self):
        for extra_state in ("activo", "Finalizado_Cobrado"):
            with self.subTest(extra_state=extra_state):
                inventory = _operaciones_servicio_inventory()
                estado = next(row for row in inventory["columns"] if row["column_name"] == "estado")
                estado["column_type"] = (
                    "enum('ACTIVO','FINALIZADO_COBRADO','CONVERTIDO_ESTADIA',"
                    f"'{extra_state}')"
                )

                contract = operaciones_servicio_contract(inventory)

                self.assertFalse(contract["valid"])
                self.assertEqual(contract["state"], "invalid")
                self.assertIn("estado ENUM must exactly match application-written states", contract["issues"])

    def test_operaciones_servicio_contract_accepts_nullable_historical_duration(self):
        inventory = _operaciones_servicio_inventory()
        duration = next(row for row in inventory["columns"] if row["column_name"] == "duracion_minutos")
        duration.update(is_nullable="YES", column_default=None)

        self.assertEqual(
            (operaciones_servicio_contract(inventory)["valid"], operaciones_servicio_contract(inventory)["state"]),
            (True, "valid"),
        )

    def test_operaciones_servicio_estado_accepts_safe_varchar_compatibility(self):
        inventory = _operaciones_servicio_inventory()
        estado = next(row for row in inventory["columns"] if row["column_name"] == "estado")
        estado.update(data_type="varchar", column_type="varchar(18)")

        self.assertTrue(operaciones_servicio_contract(inventory)["valid"])

        estado["column_type"] = "varchar(17)"
        contract = operaciones_servicio_contract(inventory)
        self.assertFalse(contract["valid"])
        self.assertTrue(any(
            issue.startswith("estado VARCHAR must fit all application-written states")
            for issue in contract["issues"]
        ))

    def test_operaciones_servicio_contract_blocks_missing_table(self):
        contract = operaciones_servicio_contract({"tables": [], "columns": [], "indexes": [], "foreign_keys": []})
        self.assertEqual((contract["valid"], contract["state"]), (False, "blocked_prerequisite"))


def _operaciones_servicio_inventory():
    columns = [
        ("id_operacion_servicio", "int", "NO", None, "PRI", "auto_increment"),
        ("patente", "varchar(10)", "NO", None, "", ""),
        ("id_tipo_vehiculo_lavado", "int", "YES", None, "", ""),
        ("fecha_hora_inicio", "datetime", "NO", None, "", ""),
        ("usuario_inicio", "varchar(50)", "NO", None, "", ""),
        ("id_ingreso_generado", "int", "YES", None, "", ""),
        ("tipo_vehiculo_lavado_snapshot", "varchar(80)", "YES", None, "", ""),
        ("valor_lavado_snapshot", "int", "NO", "0", "", ""),
        ("fecha_hora_fin", "datetime", "YES", None, "", ""),
        ("duracion_minutos", "int", "NO", "0", "", ""),
        ("usuario_fin", "varchar(50)", "YES", None, "", ""),
        ("estado", "enum('ACTIVO','FINALIZADO_COBRADO','CONVERTIDO_ESTADIA')", "NO", "ACTIVO", "", ""),
        ("cerrado", "tinyint(1)", "NO", "0", "", ""),
        ("created_at", "datetime", "NO", "CURRENT_TIMESTAMP", "", ""),
        ("updated_at", "datetime", "NO", "CURRENT_TIMESTAMP", "", "on update CURRENT_TIMESTAMP"),
    ]
    inventory = {
        "tables": [{"table_name": "operaciones_servicio", "engine": "InnoDB"}, {"table_name": "ingresos", "engine": "InnoDB"}, {"table_name": "tipos_vehiculo_lavado", "engine": "InnoDB"}],
        "columns": [{"table_name": "operaciones_servicio", "column_name": name, "data_type": column_type.split("(", 1)[0], "column_type": column_type, "is_nullable": nullable, "column_default": default, "column_key": key, "extra": extra} for name, column_type, nullable, default, key, extra in columns],
        "indexes": [],
        "foreign_keys": [],
    }
    inventory["columns"].extend([
        {"table_name": "ingresos", "column_name": "id_ingreso", "data_type": "int", "column_type": "int", "is_nullable": "NO"},
        {"table_name": "tipos_vehiculo_lavado", "column_name": "id_tipo_vehiculo_lavado", "data_type": "int", "column_type": "int", "is_nullable": "NO"},
    ])
    for index_name, table_name, names in (("PRIMARY", "operaciones_servicio", ("id_operacion_servicio",)), ("idx_operaciones_servicio_estado_fecha", "operaciones_servicio", ("estado", "fecha_hora_inicio")), ("idx_operaciones_servicio_patente", "operaciones_servicio", ("patente",)), ("idx_operaciones_servicio_ingreso_generado", "operaciones_servicio", ("id_ingreso_generado",)), ("idx_operaciones_servicio_tipo_vehiculo_lavado", "operaciones_servicio", ("id_tipo_vehiculo_lavado",)), ("idx_operaciones_servicio_cierre", "operaciones_servicio", ("cerrado", "estado", "fecha_hora_fin")), ("PRIMARY", "ingresos", ("id_ingreso",)), ("PRIMARY", "tipos_vehiculo_lavado", ("id_tipo_vehiculo_lavado",))):
        inventory["indexes"].extend({"table_name": table_name, "index_name": index_name, "column_name": name, "seq_in_index": position, "non_unique": 0 if index_name == "PRIMARY" else 1} for position, name in enumerate(names, 1))
    inventory["foreign_keys"] = [
        {"constraint_name": "fk_operaciones_servicio_ingreso_generado", "table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "referenced_table_name": "ingresos", "referenced_column_name": "id_ingreso", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"},
        {"constraint_name": "fk_operaciones_servicio_tipo_vehiculo_lavado", "table_name": "operaciones_servicio", "column_name": "id_tipo_vehiculo_lavado", "referenced_table_name": "tipos_vehiculo_lavado", "referenced_column_name": "id_tipo_vehiculo_lavado", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"},
    ]
    return inventory


if __name__ == "__main__":
    unittest.main()
