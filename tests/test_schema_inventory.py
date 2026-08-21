import re
import unittest

from app.db.schema_inventory import collect_read_only_schema_inventory, tipos_lavado_contract


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
        schema_name="parking", uppercase_row_keys=False,
    ):
        self.include_config = include_config
        self.include_schema_migrations = include_schema_migrations
        self.migration_records = migration_records or []
        self.include_tipos_lavado = include_tipos_lavado
        self.tipos_lavado_records = tipos_lavado_records or []
        self.schema_name = schema_name
        self.uppercase_row_keys = uppercase_row_keys
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
            return FakeResult(rows, uppercase_row_keys=self.uppercase_row_keys)
        if "information_schema.columns" in sql:
            rows = [
                {"table_name": "vehiculos", "column_name": "patente", "ordinal_position": 2, "column_default": None, "is_nullable": "NO", "data_type": "varchar", "column_type": "varchar(10)", "column_key": "", "extra": ""},
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
            return FakeResult(rows, uppercase_row_keys=self.uppercase_row_keys)
        if "information_schema.referential_constraints" in sql:
            return FakeResult([
                {"constraint_name": "fk_vehicle_owner", "table_name": "vehiculos", "column_name": "owner_id", "ordinal_position": 1, "referenced_table_name": "usuarios", "referenced_column_name": "id_usuario", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"},
            ], uppercase_row_keys=self.uppercase_row_keys)
        if "FROM configuracion" in sql:
            return FakeResult(
                [{"clave": "tarifa_minima", "valor": "300"}, {"clave": "modo_cobro", "valor": "hora"}],
                uppercase_row_keys=self.uppercase_row_keys,
            )
        if "FROM schema_migrations" in sql:
            return FakeResult(self.migration_records, uppercase_row_keys=self.uppercase_row_keys)
        if "FROM tipos_lavado" in sql:
            return FakeResult(self.tipos_lavado_records, uppercase_row_keys=self.uppercase_row_keys)
        raise AssertionError(f"Unexpected query: {sql}")


class SchemaInventoryTests(unittest.TestCase):
    def test_collects_sorted_read_only_inventory(self):
        conn = FakeConnection()

        inventory = collect_read_only_schema_inventory(conn)

        self.assertEqual(inventory["inventory_version"], 1)
        self.assertEqual(inventory["database"], "parking")
        self.assertEqual([row["table_name"] for row in inventory["tables"]], ["configuracion", "vehiculos"])
        self.assertEqual([row["column_name"] for row in inventory["columns"]], ["id_vehiculo", "patente"])
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


if __name__ == "__main__":
    unittest.main()
