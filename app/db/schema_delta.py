"""Read-only comparison of a schema inventory against known Desktop deltas."""

from __future__ import annotations

import json
from typing import Any

from app.db.schema_inventory import collect_read_only_schema_inventory_from_engine


SCHEMA_DELTA_VERSION = 1

DESKTOP_BASELINE_TABLES = (
    "asistencias",
    "cierres_diarios",
    "cobros_noches",
    "configuracion",
    "gastos_operacion",
    "ingresos",
    "ingresos_eliminados",
    "lavados",
    "operaciones_servicio",
    "pagos_mensuales",
    "print_job_reprints",
    "print_jobs",
    "reversiones_salida",
    "subida_precios",
    "tarifas_personalizadas",
    "tipos_lavado",
    "tipos_vehiculo_lavado",
    "usuarios",
    "usos_bano",
    "vehiculos",
)

EXPECTED_OPERACIONES_SERVICIO_FOREIGN_KEYS = (
    {
        "column_name": "id_ingreso_generado",
        "referenced_column_name": "id_ingreso",
        "referenced_table_name": "ingresos",
    },
    {
        "column_name": "id_tipo_vehiculo_lavado",
        "referenced_column_name": "id_tipo_vehiculo_lavado",
        "referenced_table_name": "tipos_vehiculo_lavado",
    },
)

NOCHES_CONFIG_KEYS = (
    "noches_activo",
    "noches_hora_fin",
    "noches_hora_inicio",
    "noches_valor",
)


def find_schema_deltas(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic, JSON-serializable findings for an existing inventory."""
    table_names = {str(row.get("table_name", "")).casefold() for row in inventory.get("tables", [])}
    expected_tables = set(DESKTOP_BASELINE_TABLES)
    foreign_keys = inventory.get("foreign_keys", [])
    actual_operaciones_foreign_keys = {
        _foreign_key_signature(row)
        for row in foreign_keys
        if str(row.get("table_name", "")).casefold() == "operaciones_servicio"
    }
    expected_operaciones_foreign_keys = {
        _foreign_key_signature(row) for row in EXPECTED_OPERACIONES_SERVICIO_FOREIGN_KEYS
    }
    metodo_pago = _find_column(inventory.get("columns", []), "pagos_mensuales", "metodo_pago")
    noches_values = _noches_values(inventory.get("config_seed_snapshot", {}))

    return {
        "delta_version": SCHEMA_DELTA_VERSION,
        "database": inventory.get("database"),
        "schema_migrations": {"present": "schema_migrations" in table_names},
        "tables": {
            "expected_desktop_baseline": list(DESKTOP_BASELINE_TABLES),
            "missing": sorted(expected_tables - table_names),
            "extra": sorted(table_names - expected_tables),
        },
        "foreign_keys": {
            "operaciones_servicio": {
                "expected": list(EXPECTED_OPERACIONES_SERVICIO_FOREIGN_KEYS),
                "missing": [
                    expected
                    for expected in EXPECTED_OPERACIONES_SERVICIO_FOREIGN_KEYS
                    if _foreign_key_signature(expected) not in actual_operaciones_foreign_keys
                ],
            },
        },
        "columns": {
            "pagos_mensuales.metodo_pago": {
                "expected_column_type": "varchar(50)",
                "actual_column_type": metodo_pago.get("column_type") if metodo_pago else None,
                "matches_expected": bool(metodo_pago and str(metodo_pago.get("column_type", "")).casefold() == "varchar(50)"),
            },
        },
        "config": {
            "noches": {
                "available": bool(inventory.get("config_seed_snapshot", {}).get("available")),
                "current_values": noches_values,
                "recommendation": "preserve_existing_values",
            },
        },
    }


def _foreign_key_signature(row: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(row.get(field, "")).casefold() for field in (
        "column_name",
        "referenced_table_name",
        "referenced_column_name",
    ))


def _find_column(columns: list[dict[str, Any]], table_name: str, column_name: str) -> dict[str, Any] | None:
    for column in columns:
        if (
            str(column.get("table_name", "")).casefold() == table_name
            and str(column.get("column_name", "")).casefold() == column_name
        ):
            return column
    return None


def _noches_values(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    values = snapshot.get("values", []) if snapshot.get("available") else []
    return sorted(
        (
            {"clave": str(row.get("clave")), "valor": row.get("valor")}
            for row in values
            if str(row.get("clave", "")).casefold() in NOCHES_CONFIG_KEYS
        ),
        key=lambda row: row["clave"],
    )


def main() -> None:
    """Collect and print schema deltas using the read-only inventory query path."""
    from app.db.database import engine

    inventory = collect_read_only_schema_inventory_from_engine(engine)
    print(json.dumps(find_schema_deltas(inventory), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
