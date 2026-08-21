"""Controlled dry-run and explicit apply support for schema migrations.

Managed migration namespace policy:
- ``schema_migration_runner.py`` owns logical IDs recorded in
  ``schema_migrations``.
- ``app/db/migrations/*.sql`` files are historical, unmanaged references unless
  explicitly imported into this runner.
- Numeric prefixes may overlap. The full managed migration ID is authoritative,
  not its numeric prefix or a historical filename.
- Future managed IDs must stay descriptive (for example,
  ``003_widen_pagos_mensuales_metodo_pago``) and do not execute a same-numbered
  historical SQL file.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import text

from app.db.schema_inventory import (
    collect_read_only_schema_inventory_from_engine,
    schema_migrations_contract,
    tipos_lavado_contract,
)


SCHEMA_MIGRATION_PLAN_VERSION = 1
MIGRATION_001_ID = "001_create_schema_migrations"
MIGRATION_002_ID = "002_create_tipos_lavado"
MANAGED_MIGRATION_IDS = (MIGRATION_001_ID, MIGRATION_002_ID)
MIGRATION_RECORD_SQL = "INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"
MIGRATION_001_RECORD_SQL = MIGRATION_RECORD_SQL
MIGRATION_002_SEED_SQL = (
    "INSERT INTO tipos_lavado (codigo, nombre, activo) "
    "VALUES ('lavado_general', 'Lavado', 1) "
    "ON DUPLICATE KEY UPDATE codigo = codigo"
)
SUCCESSFUL_APPLY_STATUSES = frozenset({"applied", "noop", "repaired"})


@dataclass(frozen=True)
class MigrationMetadata:
    migration_id: str
    description: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[MigrationMetadata, ...] = (
    MigrationMetadata(
        MIGRATION_001_ID,
        "Create the migration tracking table for future explicit apply runs.",
        ("CREATE TABLE schema_migrations (migration_id VARCHAR(255) NOT NULL PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)",),
    ),
    MigrationMetadata(
        MIGRATION_002_ID,
        "Create mutable wash-type configuration and preserve existing seed values.",
        (
            "CREATE TABLE IF NOT EXISTS tipos_lavado (\n"
            "    id_tipo_lavado INT AUTO_INCREMENT PRIMARY KEY,\n"
            "    codigo VARCHAR(50) NOT NULL UNIQUE,\n"
            "    nombre VARCHAR(80) NOT NULL,\n"
            "    activo TINYINT(1) NOT NULL DEFAULT 1,\n"
            "    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,\n"
            "    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP\n"
            ")",
        ),
    ),
)


def plan_schema_migrations(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable plan without accessing a database."""
    table_names = _table_names(inventory)
    complete = table_names is not None
    statuses = {
        MIGRATION_001_ID: _migration_001_status(inventory, table_names, complete),
        MIGRATION_002_ID: _migration_002_status(inventory, table_names, complete),
    }
    migrations = [
        {
            "id": migration.migration_id,
            "description": migration.description,
            "status": statuses[migration.migration_id],
            "sql": _planned_sql(migration, statuses[migration.migration_id], table_names),
            "will_execute": False,
        }
        for migration in MIGRATIONS
    ]
    warnings = [
        "Dry-run only: no SQL statements were executed.",
        "Apply requires explicit confirmation flags and a selected migration.",
    ]
    if not complete:
        warnings.append("Inventory does not include a tables list; migration status is unknown.")
    elif schema_migrations_contract(inventory)["valid"] is False:
        warnings.append("schema_migrations has an invalid contract; no apply SQL may be executed.")
    elif tipos_lavado_contract(inventory)["valid"] is False:
        warnings.append("tipos_lavado has an invalid contract; migration 002 may not execute SQL.")
    return {
        "plan_version": SCHEMA_MIGRATION_PLAN_VERSION,
        "mode": "dry_run",
        "database": inventory.get("database"),
        "schema_migrations": {
            "present": "schema_migrations" in table_names if complete else None,
            "contract": schema_migrations_contract(inventory),
        },
        "tipos_lavado": {
            "present": "tipos_lavado" in table_names if complete else None,
            "contract": tipos_lavado_contract(inventory),
            "seed": _tipos_lavado_seed_present(inventory),
        },
        "migrations": migrations,
        "prerequisites": [
            "Review this plan and take a database backup before any future apply run.",
            "Apply validates the expected database name before executing migration SQL.",
        ],
        "warnings": warnings,
    }


def collect_dry_run_plan(engine: Any) -> dict[str, Any]:
    return plan_schema_migrations(collect_read_only_schema_inventory_from_engine(engine))


def apply_001_create_schema_migrations(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only migration 001 after read-only inventory and preflight checks."""
    return _apply(engine, MIGRATION_001_ID, **kwargs)


def apply_002_create_tipos_lavado(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only migration 002 without overwriting mutable seed values."""
    return _apply(engine, MIGRATION_002_ID, **kwargs)


def _apply(
    engine: Any, migration_id: str, *, backup_confirmed: bool, dev_database_confirmed: bool,
    expected_database: str | None = None,
) -> dict[str, Any]:
    from app.db.schema_migration_preflight import evaluate_schema_migration_preflight

    inventory = collect_read_only_schema_inventory_from_engine(engine)
    plan = plan_schema_migrations(inventory)
    preflight = evaluate_schema_migration_preflight(inventory, plan, {
        "apply_requested": True,
        "backup_confirmed": backup_confirmed,
        "dev_database_confirmed": dev_database_confirmed,
        "expected_database": expected_database,
    })
    migration = next(item for item in plan["migrations"] if item["id"] == migration_id)
    if not expected_database or inventory.get("database") != expected_database:
        return _result(migration_id, "refused", [], ["Expected database does not match the active database; no SQL was executed."], preflight)
    if migration["status"] == "applied":
        return _result(migration_id, "noop", [], [f"Migration {migration_id[:3]} is already recorded; no SQL was executed."], preflight)
    if migration["status"] == "invalid_contract":
        return _result(migration_id, "invalid_contract", [], ["The existing table does not match the required contract; no SQL was executed."], preflight)
    if migration["status"] in {"unknown", "blocked_prerequisite", "inconsistent_state"}:
        return _result(migration_id, "refused", [], ["Migration prerequisites are not satisfied; no SQL was executed."], preflight)
    if preflight["status"] == "BLOCKED":
        return _result(migration_id, "refused", [], ["Preflight is BLOCKED; no SQL was executed."], preflight)
    if migration_id == MIGRATION_001_ID:
        return _apply_001(engine, migration["status"], preflight)
    return _apply_002(engine, migration["status"], _table_names(inventory) or set(), preflight)


def _apply_001(engine: Any, status: str, preflight: dict[str, Any]) -> dict[str, Any]:
    if status == "repair_required":
        return _record(engine, MIGRATION_001_ID, "repaired", [], preflight)
    if status != "pending":
        return _result(MIGRATION_001_ID, "refused", [], ["Migration is not pending; no SQL was executed."], preflight)
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATIONS[0].statements[0]))
            try:
                conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": MIGRATION_001_ID})
            except Exception as error:
                return _result(
                    MIGRATION_001_ID, "failed_after_create", ["CREATE TABLE"],
                    ["CREATE TABLE succeeded, but the migration record INSERT failed.", f"Retry will record migration 001: {error}"], preflight,
                )
    except Exception as error:
        return _result(MIGRATION_001_ID, "failed", [], [f"Migration 001 failed: {error}"], preflight)
    return _result(MIGRATION_001_ID, "applied", ["CREATE TABLE", "INSERT"], [], preflight)


def _apply_002(engine: Any, status: str, table_names: set[str], preflight: dict[str, Any]) -> dict[str, Any]:
    if status == "repair_required":
        return _record(engine, MIGRATION_002_ID, "repaired", [], preflight)
    if status != "pending":
        return _result(MIGRATION_002_ID, "refused", [], ["Migration is not pending; no SQL was executed."], preflight)
    executed: list[str] = []
    try:
        with engine.begin() as conn:
            if "tipos_lavado" not in table_names:
                conn.execute(text(MIGRATIONS[1].statements[0]))
                executed.append("CREATE TABLE")
            conn.execute(text(MIGRATION_002_SEED_SQL))
            executed.append("INSERT seed")
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": MIGRATION_002_ID})
            executed.append("INSERT migration record")
    except Exception as error:
        status = "failed_after_create" if executed == ["CREATE TABLE"] else "failed_after_seed" if "INSERT seed" in executed else "failed"
        return _result(MIGRATION_002_ID, status, executed, [f"Migration 002 failed after {', '.join(executed) or 'no SQL'}: {error}"], preflight)
    return _result(MIGRATION_002_ID, "applied", executed, [], preflight)


def _record(engine: Any, migration_id: str, status: str, executed: list[str], preflight: dict[str, Any]) -> dict[str, Any]:
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": migration_id})
    except Exception as error:
        return _result(migration_id, "failed", executed, [f"Migration record INSERT failed: {error}"], preflight)
    statement_type = "INSERT" if migration_id == MIGRATION_001_ID else "INSERT migration record"
    return _result(migration_id, status, [*executed, statement_type], [], preflight)


def _result(migration_id: str, status: str, executed: list[str], warnings: list[str], preflight: dict[str, Any]) -> dict[str, Any]:
    return {"migration_id": migration_id, "status": status, "executed_statements_count": len(executed), "executed_statement_types": executed, "warnings": warnings, "preflight": preflight}


def _migration_001_status(inventory: dict[str, Any], tables: set[str] | None, complete: bool) -> str:
    if not complete:
        return "unknown"
    if "schema_migrations" not in tables:
        return "pending"
    if schema_migrations_contract(inventory)["valid"] is not True:
        return "invalid_contract"
    recorded = _migration_recorded(inventory, MIGRATION_001_ID)
    if recorded is None:
        return "unknown"
    return "applied" if recorded else "repair_required"


def _migration_002_status(inventory: dict[str, Any], tables: set[str] | None, complete: bool) -> str:
    if not complete:
        return "unknown"
    recorded = _migration_recorded(inventory, MIGRATION_002_ID)
    if recorded is True:
        if "tipos_lavado" not in tables:
            return "inconsistent_state"
        if tipos_lavado_contract(inventory)["valid"] is False:
            return "invalid_contract"
        return "applied"
    if _migration_recorded(inventory, MIGRATION_001_ID) is not True:
        return "blocked_prerequisite"
    if tipos_lavado_contract(inventory)["valid"] is False:
        return "invalid_contract"
    if "tipos_lavado" not in tables or _tipos_lavado_seed_present(inventory) is False:
        return "pending"
    if _tipos_lavado_seed_present(inventory) is True:
        return "repair_required"
    return "unknown"


def _migration_recorded(inventory: dict[str, Any], migration_id: str) -> bool | None:
    snapshot = inventory.get("migration_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("available") is not True or not isinstance(snapshot.get("records"), list):
        return None
    return any(isinstance(row, dict) and row.get("migration_id") == migration_id for row in snapshot["records"])


def _tipos_lavado_seed_present(inventory: dict[str, Any]) -> bool | None:
    snapshot = inventory.get("tipos_lavado_seed_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("available") is not True or not isinstance(snapshot.get("records"), list):
        return None
    return any(isinstance(row, dict) and row.get("codigo") == "lavado_general" for row in snapshot["records"])


def _table_names(inventory: dict[str, Any]) -> set[str] | None:
    tables = inventory.get("tables")
    if not isinstance(tables, list):
        return None
    return {str(row.get("table_name", "")).casefold() for row in tables if isinstance(row, dict)}


def _planned_sql(migration: MigrationMetadata, status: str, tables: set[str] | None) -> list[str]:
    if status == "repair_required":
        return [MIGRATION_RECORD_SQL]
    if status != "pending":
        return []
    if migration.migration_id == MIGRATION_002_ID and tables is not None and "tipos_lavado" in tables:
        return [MIGRATION_002_SEED_SQL, MIGRATION_RECORD_SQL]
    if migration.migration_id == MIGRATION_002_ID:
        return [*migration.statements, MIGRATION_002_SEED_SQL, MIGRATION_RECORD_SQL]
    return list(migration.statements)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan migrations or explicitly apply one migration.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-001-create-schema-migrations", action="store_true")
    parser.add_argument("--apply-002-create-tipos-lavado", action="store_true")
    parser.add_argument("--confirm-dev-db", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    parser.add_argument("--expected-database")
    args = parser.parse_args(argv)
    apply_flags = [args.apply_001_create_schema_migrations, args.apply_002_create_tipos_lavado]
    if args.dry_run and any(apply_flags) or sum(apply_flags) > 1:
        parser.error("choose exactly one of --dry-run or one explicit apply flag")
    if not args.dry_run and not any(apply_flags):
        parser.error("refusing to run without --dry-run or --apply explicit migration flag")
    if any(apply_flags) and not args.expected_database:
        parser.error("--expected-database is required for apply")
    if any(apply_flags) and not args.confirm_dev_db:
        parser.error("--confirm-dev-db is required for apply")
    if any(apply_flags) and not args.backup_confirmed:
        parser.error("--backup-confirmed is required for apply")
    from app.db.database import engine
    if args.dry_run:
        result = collect_dry_run_plan(engine)
    else:
        apply = apply_001_create_schema_migrations if args.apply_001_create_schema_migrations else apply_002_create_tipos_lavado
        result = apply(engine, backup_confirmed=args.backup_confirmed, dev_database_confirmed=args.confirm_dev_db, expected_database=args.expected_database)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if args.dry_run or result.get("status") in SUCCESSFUL_APPLY_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
