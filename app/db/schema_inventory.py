"""Read-only MySQL schema inventory for migration auditing."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, TYPE_CHECKING

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


SCHEMA_INVENTORY_VERSION = 1

# Stable, migration-relevant configuration values. The query runs only when the
# existing schema reports the configuracion table.
CONFIG_SEED_KEYS = (
    "modo_cobro",
    "tarifa_minima",
    "tarifa_por_hora",
    "tarifa_hora",
    "tarifa_mensual",
    "noches_activo",
    "noches_hora_inicio",
    "noches_hora_fin",
    "noches_valor",
)

_CURRENT_SCHEMA_SQL = "SELECT DATABASE() AS schema_name"
_TABLES_SQL = """
    SELECT table_name, table_type, engine, table_collation
    FROM information_schema.tables
    WHERE table_schema = :schema_name
"""
_COLUMNS_SQL = """
    SELECT table_name, column_name, ordinal_position, column_default,
            is_nullable, data_type, column_type, column_key, extra,
            character_set_name, collation_name
    FROM information_schema.columns
    WHERE table_schema = :schema_name
"""
_INDEXES_SQL = """
    SELECT table_name, index_name, non_unique, seq_in_index, column_name,
           collation, index_type
    FROM information_schema.statistics
    WHERE table_schema = :schema_name
"""
_FOREIGN_KEYS_SQL = """
    SELECT rc.constraint_name, rc.table_name, kcu.column_name,
           kcu.ordinal_position, kcu.referenced_table_name,
           kcu.referenced_column_name, rc.update_rule, rc.delete_rule
    FROM information_schema.referential_constraints AS rc
    JOIN information_schema.key_column_usage AS kcu
      ON kcu.constraint_schema = rc.constraint_schema
     AND kcu.constraint_name = rc.constraint_name
     AND kcu.table_name = rc.table_name
    WHERE rc.constraint_schema = :schema_name
"""
_CONFIG_SQL = """
    SELECT clave, valor
    FROM configuracion
    WHERE clave IN :config_keys
"""
_SCHEMA_MIGRATIONS_SQL = """
    SELECT migration_id, applied_at
    FROM schema_migrations
"""
_TIPOS_LAVADO_SEED_SQL = """
    SELECT codigo, nombre, activo
    FROM tipos_lavado
    WHERE codigo = :codigo
"""
TIPOS_LAVADO_SEED_CODE = "lavado_general"


def collect_read_only_schema_inventory(conn: Connection) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable inventory without mutating MySQL."""
    schema_name = conn.execute(text(_CURRENT_SCHEMA_SQL)).scalar()
    if not schema_name:
        raise RuntimeError("The active database name is required for schema inventory")

    params = {"schema_name": str(schema_name)}
    tables = _read_rows(conn, _TABLES_SQL, params, ("table_name",))
    columns = _read_rows(conn, _COLUMNS_SQL, params, ("table_name", "ordinal_position", "column_name"))
    indexes = _read_rows(conn, _INDEXES_SQL, params, ("table_name", "index_name", "seq_in_index", "column_name"))
    foreign_keys = _read_rows(
        conn,
        _FOREIGN_KEYS_SQL,
        params,
        ("table_name", "constraint_name", "ordinal_position", "column_name"),
    )
    config_available = any(row["table_name"].casefold() == "configuracion" for row in tables)
    schema_migrations_available = any(
        row["table_name"].casefold() == "schema_migrations" for row in tables
    )
    config_values = []
    if config_available:
        config_query = text(_CONFIG_SQL).bindparams(bindparam("config_keys", expanding=True))
        config_values = _read_rows(conn, config_query, {"config_keys": CONFIG_SEED_KEYS}, ("clave",))
    migration_contract = schema_migrations_contract({
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
    })
    migration_records = []
    if migration_contract["valid"] is True:
        migration_records = _read_rows(conn, _SCHEMA_MIGRATIONS_SQL, {}, ("migration_id", "applied_at"))
    tipos_contract = tipos_lavado_contract({
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
    })
    tipos_lavado_seed = []
    if tipos_contract["valid"] is True:
        tipos_lavado_seed = _read_rows(
            conn, _TIPOS_LAVADO_SEED_SQL, {"codigo": TIPOS_LAVADO_SEED_CODE}, ("codigo",)
        )

    return {
        "inventory_version": SCHEMA_INVENTORY_VERSION,
        "database": str(schema_name),
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
        "foreign_keys": foreign_keys,
        "config_seed_snapshot": {
            "source_table": "configuracion",
            "available": config_available,
            "values": config_values,
        },
        "migration_snapshot": {
            "source_table": "schema_migrations",
            "available": schema_migrations_available,
            "contract": migration_contract,
            "records": migration_records,
        },
        "tipos_lavado_seed_snapshot": {
            "source_table": "tipos_lavado",
            "available": tipos_contract["valid"] is True,
            "contract": tipos_contract,
            "records": tipos_lavado_seed,
        },
    }


def collect_read_only_schema_inventory_from_engine(engine: Engine) -> dict[str, Any]:
    """Collect a read-only inventory using an existing SQLAlchemy engine."""
    with engine.connect() as conn:
        return collect_read_only_schema_inventory(conn)


def schema_migrations_contract(inventory: dict[str, Any]) -> dict[str, Any]:
    """Validate the tracking table shape required by migration 001."""
    table_names = {
        str(row.get("table_name", "")).casefold()
        for row in inventory.get("tables", [])
        if isinstance(row, dict)
    }
    if "schema_migrations" not in table_names:
        return {"valid": None, "issues": []}

    columns = {
        str(row.get("column_name", "")).casefold(): row
        for row in inventory.get("columns", [])
        if isinstance(row, dict) and str(row.get("table_name", "")).casefold() == "schema_migrations"
    }
    indexes = [
        row for row in inventory.get("indexes", [])
        if isinstance(row, dict) and str(row.get("table_name", "")).casefold() == "schema_migrations"
    ]
    issues = []
    migration_id = columns.get("migration_id")
    if migration_id is None:
        issues.append("migration_id column is missing")
    else:
        if str(migration_id.get("column_type", "")).casefold() != "varchar(255)":
            issues.append("migration_id column_type must be varchar(255)")
        if str(migration_id.get("is_nullable", "")).casefold() != "no":
            issues.append("migration_id must be NOT NULL")
        if not _migration_id_is_primary_key(migration_id, indexes):
            issues.append("migration_id must be the sole primary key column")

    applied_at = columns.get("applied_at")
    if applied_at is None:
        issues.append("applied_at column is missing")
    else:
        if (
            str(applied_at.get("data_type", "")).casefold() != "datetime"
            and str(applied_at.get("column_type", "")).casefold() != "datetime"
        ):
            issues.append("applied_at must be datetime")
        if str(applied_at.get("is_nullable", "")).casefold() != "no":
            issues.append("applied_at must be NOT NULL")
        if not _has_current_timestamp_default(applied_at.get("column_default")):
            issues.append("applied_at default must be CURRENT_TIMESTAMP")
    return {"valid": not issues, "issues": issues}


def tipos_lavado_contract(inventory: dict[str, Any]) -> dict[str, Any]:
    """Validate the mutable wash-type configuration table required by migration 002."""
    table_names = {
        str(row.get("table_name", "")).casefold()
        for row in inventory.get("tables", [])
        if isinstance(row, dict)
    }
    if "tipos_lavado" not in table_names:
        return {"valid": None, "issues": []}

    columns = {
        str(row.get("column_name", "")).casefold(): row
        for row in inventory.get("columns", [])
        if isinstance(row, dict) and str(row.get("table_name", "")).casefold() == "tipos_lavado"
    }
    indexes = [
        row for row in inventory.get("indexes", [])
        if isinstance(row, dict) and str(row.get("table_name", "")).casefold() == "tipos_lavado"
    ]
    issues = []
    _require_column(
        issues, columns, "id_tipo_lavado", "int", nullable=False, primary_key=True,
        auto_increment=True, indexes=indexes,
    )
    _require_column(issues, columns, "codigo", "varchar(50)", nullable=False, unique=True, indexes=indexes)
    _require_column(issues, columns, "nombre", "varchar(80)", nullable=False)
    _require_column(issues, columns, "activo", "tinyint(1)", nullable=False, default="1")
    _require_column(issues, columns, "created_at", "datetime", nullable=False, default="CURRENT_TIMESTAMP")
    _require_column(
        issues, columns, "updated_at", "datetime", nullable=False, default="CURRENT_TIMESTAMP", on_update=True
    )
    return {"valid": not issues, "issues": issues}


def pagos_mensuales_metodo_pago_contract(inventory: dict[str, Any]) -> dict[str, Any]:
    """Classify the monthly-payment method column for the controlled widen."""
    table_names = {
        str(row.get("table_name", "")).casefold()
        for row in inventory.get("tables", [])
        if isinstance(row, dict)
    }
    if "pagos_mensuales" not in table_names:
        return {"valid": None, "widen_safe": False, "state": "missing_table", "issues": []}

    column = next((
        row for row in inventory.get("columns", [])
        if isinstance(row, dict)
        and str(row.get("table_name", "")).casefold() == "pagos_mensuales"
        and str(row.get("column_name", "")).casefold() == "metodo_pago"
    ), None)
    if column is None:
        return {"valid": False, "widen_safe": False, "state": "missing_column", "issues": ["metodo_pago column is missing"]}

    issues = []
    table = next((
        row for row in inventory.get("tables", [])
        if isinstance(row, dict)
        and str(row.get("table_name", "")).casefold() == "pagos_mensuales"
    ), None)
    if str(column.get("data_type", "")).casefold() != "varchar":
        issues.append("metodo_pago data_type must be varchar")
    if str(column.get("is_nullable", "")).casefold() != "yes":
        issues.append("metodo_pago must be NULL")
    if column.get("column_default") is not None:
        issues.append("metodo_pago default must be NULL")
    if str(column.get("extra") or "").strip():
        issues.append("metodo_pago extra must be empty")
    table_collation = str(table.get("table_collation") or "").casefold() if table else ""
    column_collation = str(column.get("collation_name") or "").casefold()
    if not table_collation or not column_collation or column_collation != table_collation:
        issues.append("metodo_pago collation must match the table default")
    character_set = str(column.get("character_set_name") or "").casefold()
    if not character_set or character_set != _charset_from_collation(table_collation):
        issues.append("metodo_pago character set must match the table default")
    column_type = str(column.get("column_type", "")).casefold()
    if not issues and column_type == "varchar(50)":
        return {"valid": True, "widen_safe": False, "state": "valid", "issues": []}
    if not issues and column_type == "varchar(40)":
        return {"valid": False, "widen_safe": True, "state": "widen_safe", "issues": []}
    if not issues:
        issues.append("metodo_pago column_type must be varchar(40) or varchar(50)")
    return {"valid": False, "widen_safe": False, "state": "invalid", "issues": issues}


def _require_column(
    issues: list[str], columns: dict[str, dict[str, Any]], name: str, column_type: str, *, nullable: bool,
    primary_key: bool = False, auto_increment: bool = False, unique: bool = False,
    indexes: list[dict[str, Any]] | None = None, default: str | None = None, on_update: bool = False,
) -> None:
    column = columns.get(name)
    if column is None:
        issues.append(f"{name} column is missing")
        return
    if str(column.get("column_type", "")).casefold() != column_type:
        issues.append(f"{name} column_type must be {column_type}")
    if str(column.get("is_nullable", "")).casefold() != ("yes" if nullable else "no"):
        issues.append(f"{name} must be {'NULL' if nullable else 'NOT NULL'}")
    if primary_key and not _single_column_index(column, indexes or [], "primary"):
        issues.append(f"{name} must be the sole primary key column")
    if auto_increment and "auto_increment" not in str(column.get("extra", "")).casefold():
        issues.append(f"{name} must be AUTO_INCREMENT")
    if unique and not _single_column_unique_index(column, indexes or []):
        issues.append(f"{name} must be UNIQUE")
    if default is not None and (
        not _has_current_timestamp_default(column.get("column_default"))
        if default == "CURRENT_TIMESTAMP"
        else str(column.get("column_default")) != default
    ):
        issues.append(f"{name} default must be {default}")
    if on_update and "on update current_timestamp" not in " ".join(str(column.get("extra", "")).casefold().split()):
        issues.append(f"{name} must update with CURRENT_TIMESTAMP")


def _single_column_index(column: dict[str, Any], indexes: list[dict[str, Any]], index_name: str) -> bool:
    matches = [index for index in indexes if str(index.get("index_name", "")).casefold() == index_name]
    return (
        len(matches) == 1
        and str(matches[0].get("column_name", "")).casefold() == str(column.get("column_name", "")).casefold()
        and str(matches[0].get("seq_in_index", "")) == "1"
    )


def _single_column_unique_index(column: dict[str, Any], indexes: list[dict[str, Any]]) -> bool:
    indexes_by_name: dict[str, list[dict[str, Any]]] = {}
    for index in indexes:
        index_name = str(index.get("index_name", "")).casefold()
        indexes_by_name.setdefault(index_name, []).append(index)
    return any(
        len(index_columns) == 1
        and str(index_columns[0].get("column_name", "")).casefold()
        == str(column.get("column_name", "")).casefold()
        and str(index_columns[0].get("seq_in_index", "")) == "1"
        and str(index_columns[0].get("non_unique", "")).casefold() in {"0", "false"}
        for index_columns in indexes_by_name.values()
    )


def _migration_id_is_primary_key(column: dict[str, Any], indexes: list[dict[str, Any]]) -> bool:
    primary_key_columns = [
        index for index in indexes
        if str(index.get("index_name", "")).casefold() == "primary"
    ]
    return (
        len(primary_key_columns) == 1
        and str(primary_key_columns[0].get("column_name", "")).casefold() == "migration_id"
        and str(primary_key_columns[0].get("seq_in_index", "")) == "1"
        and str(column.get("column_key", "")).casefold() == "pri"
    )


def _has_current_timestamp_default(value: Any) -> bool:
    return str(value or "").casefold().replace("()", "") == "current_timestamp"


def _charset_from_collation(collation: str) -> str:
    return collation.split("_", 1)[0]


def _read_rows(
    conn: Connection,
    query: Any,
    params: dict[str, Any],
    sort_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = [_json_serializable(dict(row)) for row in conn.execute(text(query) if isinstance(query, str) else query, params).mappings().all()]
    return sorted(rows, key=lambda row: tuple(_sort_value(row.get(field)) for field in sort_fields))


def _json_serializable(row: dict[str, Any]) -> dict[str, Any]:
    return {key.lower(): _json_value(value) for key, value in row.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sort_value(value: Any) -> tuple[int, Any]:
    return (value is not None, value)


def main() -> None:
    """Print the current read-only inventory as JSON."""
    from app.db.database import engine

    inventory = collect_read_only_schema_inventory_from_engine(engine)
    print(json.dumps(inventory, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
