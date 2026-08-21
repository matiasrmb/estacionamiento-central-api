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
    config_values = []
    if config_available:
        config_query = text(_CONFIG_SQL).bindparams(bindparam("config_keys", expanding=True))
        config_values = _read_rows(conn, config_query, {"config_keys": CONFIG_SEED_KEYS}, ("clave",))

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
    }


def collect_read_only_schema_inventory_from_engine(engine: Engine) -> dict[str, Any]:
    """Collect a read-only inventory using an existing SQLAlchemy engine."""
    with engine.connect() as conn:
        return collect_read_only_schema_inventory(conn)


def _read_rows(
    conn: Connection,
    query: Any,
    params: dict[str, Any],
    sort_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = [_json_serializable(dict(row)) for row in conn.execute(text(query) if isinstance(query, str) else query, params).mappings().all()]
    return sorted(rows, key=lambda row: tuple(_sort_value(row.get(field)) for field in sort_fields))


def _json_serializable(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


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
