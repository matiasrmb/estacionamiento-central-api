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
           is_nullable, data_type, column_type, column_key, extra
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
