import re
import unittest

from app.db.schema_inventory import collect_read_only_schema_inventory


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
    def __init__(self, *, include_config=True, schema_name="parking", uppercase_row_keys=False):
        self.include_config = include_config
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
            return FakeResult(rows, uppercase_row_keys=self.uppercase_row_keys)
        if "information_schema.columns" in sql:
            return FakeResult([
                {"table_name": "vehiculos", "column_name": "patente", "ordinal_position": 2, "column_default": None, "is_nullable": "NO", "data_type": "varchar", "column_type": "varchar(10)", "column_key": "", "extra": ""},
                {"table_name": "vehiculos", "column_name": "id_vehiculo", "ordinal_position": 1, "column_default": None, "is_nullable": "NO", "data_type": "int", "column_type": "int", "column_key": "PRI", "extra": "auto_increment"},
            ], uppercase_row_keys=self.uppercase_row_keys)
        if "information_schema.statistics" in sql:
            return FakeResult([
                {"table_name": "vehiculos", "index_name": "idx_patente", "non_unique": 1, "seq_in_index": 1, "column_name": "patente", "collation": "A", "index_type": "BTREE"},
                {"table_name": "vehiculos", "index_name": "PRIMARY", "non_unique": 0, "seq_in_index": 1, "column_name": "id_vehiculo", "collation": "A", "index_type": "BTREE"},
            ], uppercase_row_keys=self.uppercase_row_keys)
        if "information_schema.referential_constraints" in sql:
            return FakeResult([
                {"constraint_name": "fk_vehicle_owner", "table_name": "vehiculos", "column_name": "owner_id", "ordinal_position": 1, "referenced_table_name": "usuarios", "referenced_column_name": "id_usuario", "update_rule": "RESTRICT", "delete_rule": "RESTRICT"},
            ], uppercase_row_keys=self.uppercase_row_keys)
        if "FROM configuracion" in sql:
            return FakeResult(
                [{"clave": "tarifa_minima", "valor": "300"}, {"clave": "modo_cobro", "valor": "hora"}],
                uppercase_row_keys=self.uppercase_row_keys,
            )
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

    def test_normalizes_uppercase_pymysql_mapping_keys(self):
        inventory = collect_read_only_schema_inventory(FakeConnection(uppercase_row_keys=True))

        self.assertEqual(inventory["tables"][0]["table_name"], "configuracion")
        self.assertEqual(inventory["columns"][0]["column_name"], "id_vehiculo")
        self.assertEqual(inventory["indexes"][0]["index_name"], "PRIMARY")
        self.assertEqual(inventory["foreign_keys"][0]["constraint_name"], "fk_vehicle_owner")
        self.assertEqual(inventory["config_seed_snapshot"]["values"][0], {"clave": "modo_cobro", "valor": "hora"})

    def test_requires_active_database_name(self):
        conn = FakeConnection(schema_name=None)

        with self.assertRaisesRegex(RuntimeError, "active database name"):
            collect_read_only_schema_inventory(conn)


if __name__ == "__main__":
    unittest.main()
