import json
import unittest

from app.db.schema_delta import DESKTOP_BASELINE_TABLES, find_schema_deltas


class SchemaDeltaTests(unittest.TestCase):
    def test_reports_known_dev_database_deltas(self):
        inventory = _inventory(
            tables=[table for table in DESKTOP_BASELINE_TABLES if table != "tipos_lavado"],
            metodo_pago_type="varchar(40)",
            foreign_keys=[],
            noches_values=[
                {"clave": "noches_hora_inicio", "valor": "22:00"},
                {"clave": "noches_hora_fin", "valor": "08:00"},
            ],
        )

        findings = find_schema_deltas(inventory)

        self.assertEqual(findings["schema_migrations"], {"present": False})
        self.assertEqual(findings["tables"]["missing"], ["tipos_lavado"])
        self.assertEqual(
            findings["foreign_keys"]["operaciones_servicio"]["missing"],
            [
                {"column_name": "id_ingreso_generado", "referenced_column_name": "id_ingreso", "referenced_table_name": "ingresos"},
                {"column_name": "id_tipo_vehiculo_lavado", "referenced_column_name": "id_tipo_vehiculo_lavado", "referenced_table_name": "tipos_vehiculo_lavado"},
            ],
        )
        self.assertEqual(findings["columns"]["pagos_mensuales.metodo_pago"], {
            "expected_column_type": "varchar(50)",
            "actual_column_type": "varchar(40)",
            "matches_expected": False,
        })
        self.assertEqual(findings["config"]["noches"], {
            "available": True,
            "current_values": [
                {"clave": "noches_hora_fin", "valor": "08:00"},
                {"clave": "noches_hora_inicio", "valor": "22:00"},
            ],
            "recommendation": "preserve_existing_values",
        })
        self.assertEqual(json.loads(json.dumps(findings)), findings)

    def test_accepts_clean_desktop_baseline(self):
        inventory = _inventory(
            tables=[*DESKTOP_BASELINE_TABLES, "schema_migrations"],
            metodo_pago_type="VARCHAR(50)",
            foreign_keys=[
                {"table_name": "operaciones_servicio", "column_name": "id_tipo_vehiculo_lavado", "referenced_table_name": "tipos_vehiculo_lavado", "referenced_column_name": "id_tipo_vehiculo_lavado"},
                {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "referenced_table_name": "ingresos", "referenced_column_name": "id_ingreso"},
            ],
            noches_values=[{"clave": "noches_activo", "valor": "1"}],
        )

        findings = find_schema_deltas(inventory)

        self.assertEqual(findings["schema_migrations"], {"present": True})
        self.assertEqual(findings["tables"]["missing"], [])
        self.assertEqual(findings["tables"]["extra"], ["schema_migrations"])
        self.assertEqual(findings["foreign_keys"]["operaciones_servicio"]["missing"], [])
        self.assertTrue(findings["columns"]["pagos_mensuales.metodo_pago"]["matches_expected"])
        self.assertTrue(findings["columns"]["ingresos.en_lavado"]["matches_expected"])
        self.assertEqual(findings["config"]["noches"]["recommendation"], "preserve_existing_values")

    def test_rejects_en_lavado_with_correct_type_but_wrong_nullability_or_default(self):
        for overrides in ({"is_nullable": "NO"}, {"column_default": None}):
            with self.subTest(overrides=overrides):
                inventory = _inventory(
                    tables=DESKTOP_BASELINE_TABLES,
                    metodo_pago_type="varchar(50)",
                    foreign_keys=[],
                    noches_values=[],
                )
                next(column for column in inventory["columns"] if column["column_name"] == "en_lavado").update(overrides)

                findings = find_schema_deltas(inventory)

                self.assertFalse(findings["columns"]["ingresos.en_lavado"]["matches_expected"])

    def test_output_is_deterministic_for_equivalent_unordered_inventory(self):
        ordered = _inventory(
            tables=[*DESKTOP_BASELINE_TABLES, "schema_migrations"],
            metodo_pago_type="varchar(50)",
            foreign_keys=[
                {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "referenced_table_name": "ingresos", "referenced_column_name": "id_ingreso"},
                {"table_name": "operaciones_servicio", "column_name": "id_tipo_vehiculo_lavado", "referenced_table_name": "tipos_vehiculo_lavado", "referenced_column_name": "id_tipo_vehiculo_lavado"},
            ],
            noches_values=[
                {"clave": "noches_hora_fin", "valor": "08:00"},
                {"clave": "noches_hora_inicio", "valor": "22:00"},
            ],
        )
        unordered = _inventory(
            tables=["schema_migrations", *reversed(DESKTOP_BASELINE_TABLES)],
            metodo_pago_type="varchar(50)",
            foreign_keys=[
                {"table_name": "operaciones_servicio", "column_name": "id_tipo_vehiculo_lavado", "referenced_table_name": "tipos_vehiculo_lavado", "referenced_column_name": "id_tipo_vehiculo_lavado"},
                {"table_name": "operaciones_servicio", "column_name": "id_ingreso_generado", "referenced_table_name": "ingresos", "referenced_column_name": "id_ingreso"},
            ],
            noches_values=[
                {"clave": "noches_hora_inicio", "valor": "22:00"},
                {"clave": "noches_hora_fin", "valor": "08:00"},
            ],
        )

        self.assertEqual(find_schema_deltas(unordered), find_schema_deltas(ordered))

    def test_degrades_safely_when_optional_inventory_parts_are_absent(self):
        inventory = _inventory(
            tables=DESKTOP_BASELINE_TABLES,
            metodo_pago_type=None,
            foreign_keys=[],
            noches_values=[],
            config_available=False,
        )

        findings = find_schema_deltas(inventory)

        self.assertEqual(findings["columns"]["pagos_mensuales.metodo_pago"], {
            "expected_column_type": "varchar(50)",
            "actual_column_type": None,
            "matches_expected": False,
        })
        self.assertEqual(findings["config"]["noches"], {
            "available": False,
            "current_values": [],
            "recommendation": "preserve_existing_values",
        })


def _inventory(*, tables, metodo_pago_type, foreign_keys, noches_values, config_available=True):
    columns = []
    if metodo_pago_type is not None:
        columns.append({
            "table_name": "pagos_mensuales",
            "column_name": "metodo_pago",
            "column_type": metodo_pago_type,
        })
    columns.append({
        "table_name": "ingresos",
        "column_name": "en_lavado",
        "column_type": "tinyint(1)",
        "is_nullable": "YES",
        "column_default": "0",
    })
    return {
        "inventory_version": 1,
        "database": "parking",
        "tables": [{"table_name": table} for table in tables],
        "columns": columns,
        "foreign_keys": foreign_keys,
        "config_seed_snapshot": {
            "available": config_available,
            "values": noches_values,
        },
    }


if __name__ == "__main__":
    unittest.main()
