"""Controlled dry-run and apply support for the initial schema migration."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import text

from app.db.schema_inventory import (
    collect_read_only_schema_inventory_from_engine,
    schema_migrations_contract,
)


SCHEMA_MIGRATION_PLAN_VERSION = 1


@dataclass(frozen=True)
class MigrationMetadata:
    """Immutable definition of a future migration, including unexecuted SQL."""

    migration_id: str
    description: str
    statements: tuple[str, ...]


MIGRATIONS: tuple[MigrationMetadata, ...] = (
    MigrationMetadata(
        migration_id="001_create_schema_migrations",
        description="Create the migration tracking table for future explicit apply runs.",
        statements=(
            "CREATE TABLE schema_migrations ("
            "migration_id VARCHAR(255) NOT NULL PRIMARY KEY, "
            "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")",
        ),
    ),
)

MIGRATION_001_ID = "001_create_schema_migrations"
MIGRATION_001_RECORD_SQL = "INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"
SUCCESSFUL_APPLY_STATUSES = frozenset({"applied", "noop", "repaired"})


def plan_schema_migrations(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable plan without accessing a database."""
    table_names = _table_names(inventory)
    inventory_complete = table_names is not None
    migrations = []

    for migration in MIGRATIONS:
        if migration.migration_id == "001_create_schema_migrations":
            if not inventory_complete:
                status = "unknown"
            elif "schema_migrations" not in table_names:
                status = "pending"
            elif schema_migrations_contract(inventory)["valid"] is not True:
                status = "invalid_contract"
            elif _migration_001_recorded(inventory) is True:
                status = "applied"
            elif _migration_001_recorded(inventory) is False:
                status = "repair_required"
            else:
                status = "unknown"
        else:
            status = "blocked"
        migrations.append({
            "id": migration.migration_id,
            "description": migration.description,
            "status": status,
            "sql": _planned_sql(migration, status),
            "will_execute": False,
        })

    warnings = [
        "Dry-run only: no SQL statements were executed.",
        "Apply requires explicit confirmation flags and supports only migration 001.",
    ]
    if not inventory_complete:
        warnings.append("Inventory does not include a tables list; migration status is unknown.")
    elif schema_migrations_contract(inventory)["valid"] is False:
        warnings.append("schema_migrations has an invalid contract; no apply SQL may be executed.")

    return {
        "plan_version": SCHEMA_MIGRATION_PLAN_VERSION,
        "mode": "dry_run",
        "database": inventory.get("database"),
        "schema_migrations": {
            "present": "schema_migrations" in table_names if inventory_complete else None,
            "contract": schema_migrations_contract(inventory),
        },
        "migrations": migrations,
        "prerequisites": [
            "Review this plan and take a database backup before any future apply run.",
            "Apply validates the expected database name before executing migration SQL.",
        ],
        "warnings": warnings,
    }


def collect_dry_run_plan(engine: Any) -> dict[str, Any]:
    """Collect read-only inventory through an engine, then build a non-mutating plan."""
    return plan_schema_migrations(collect_read_only_schema_inventory_from_engine(engine))


def apply_001_create_schema_migrations(
    engine: Any,
    *,
    backup_confirmed: bool,
    dev_database_confirmed: bool,
    expected_database: str | None = None,
) -> dict[str, Any]:
    """Apply only migration 001 after read-only inventory and preflight checks."""
    from app.db.schema_migration_preflight import evaluate_schema_migration_preflight

    inventory = collect_read_only_schema_inventory_from_engine(engine)
    plan = plan_schema_migrations(inventory)
    preflight = evaluate_schema_migration_preflight(inventory, plan, {
        "apply_requested": True,
        "backup_confirmed": backup_confirmed,
        "dev_database_confirmed": dev_database_confirmed,
        "expected_database": expected_database,
    })
    migration = plan["migrations"][0]
    warnings = [
        "MySQL CREATE TABLE can implicitly commit, so creating the table and recording it cannot be fully atomic.",
    ]

    if not expected_database or inventory.get("database") != expected_database:
        return _apply_result(
            "refused", 0, [],
            ["Expected database does not match the active database; no SQL was executed."], preflight,
        )
    if migration["status"] == "invalid_contract":
        return _apply_result(
            "invalid_contract", 0, [],
            ["schema_migrations does not match migration 001's required contract; no SQL was executed."], preflight,
        )
    if migration["status"] == "unknown":
        return _apply_result("refused", 0, [], ["Migration status is unknown; no SQL was executed."], preflight)
    if preflight["status"] == "BLOCKED":
        return _apply_result("refused", 0, [], ["Preflight is BLOCKED; no SQL was executed."], preflight)
    if migration["status"] == "applied":
        return _apply_result("noop", 0, [], ["Migration 001 is already recorded; no SQL was executed."], preflight)
    if migration["status"] == "repair_required":
        try:
            with engine.begin() as conn:
                conn.execute(text(MIGRATION_001_RECORD_SQL), {"migration_id": MIGRATION_001_ID})
        except Exception as error:
            return _apply_result("failed", 0, [], [f"Migration record INSERT failed: {error}"], preflight)
        return _apply_result("repaired", 1, ["INSERT"], warnings, preflight)
    if migration["status"] != "pending":
        return _apply_result("refused", 0, [], ["Migration is not pending; no SQL was executed."], preflight)

    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATIONS[0].statements[0]))
            try:
                conn.execute(text(MIGRATION_001_RECORD_SQL), {"migration_id": MIGRATION_001_ID})
            except Exception as error:
                return _apply_result(
                    "failed_after_create", 1, ["CREATE TABLE"],
                    [
                        "CREATE TABLE succeeded, but the migration record INSERT failed.",
                        f"Retry after resolving the INSERT failure; the retry will record migration 001 without CREATE: {error}",
                    ], preflight,
                )
    except Exception as error:
        return _apply_result("failed", 0, [], [f"CREATE TABLE failed: {error}"], preflight)
    return _apply_result("applied", 2, ["CREATE TABLE", "INSERT"], warnings, preflight)


def _apply_result(
    status: str,
    executed_statements_count: int,
    executed_statement_types: list[str],
    warnings: list[str],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    return {
        "migration_id": MIGRATION_001_ID,
        "status": status,
        "executed_statements_count": executed_statements_count,
        "executed_statement_types": executed_statement_types,
        "warnings": warnings,
        "preflight": preflight,
    }


def _table_names(inventory: dict[str, Any]) -> set[str] | None:
    tables = inventory.get("tables")
    if not isinstance(tables, list):
        return None
    return {
        str(row.get("table_name", "")).casefold()
        for row in tables
        if isinstance(row, dict)
    }


def _migration_001_recorded(inventory: dict[str, Any]) -> bool | None:
    snapshot = inventory.get("migration_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("available") is not True:
        return None
    records = snapshot.get("records")
    if not isinstance(records, list):
        return None
    return any(
        isinstance(record, dict) and record.get("migration_id") == MIGRATION_001_ID
        for record in records
    )


def _planned_sql(migration: MigrationMetadata, status: str) -> list[str]:
    if status == "pending":
        return list(migration.statements)
    if status == "repair_required":
        return [MIGRATION_001_RECORD_SQL]
    return []


def main(argv: Sequence[str] | None = None) -> int:
    """Print a dry-run plan or explicitly apply only migration 001."""
    parser = argparse.ArgumentParser(description="Plan migrations or explicitly apply migration 001.")
    parser.add_argument("--dry-run", action="store_true", help="collect inventory and print a non-mutating plan")
    parser.add_argument("--apply-001-create-schema-migrations", action="store_true", help="apply only migration 001")
    parser.add_argument("--confirm-dev-db", action="store_true", help="confirm the target is a development database")
    parser.add_argument("--backup-confirmed", action="store_true", help="confirm a current database backup exists")
    parser.add_argument("--expected-database", help="require this exact active database name when applying")
    args = parser.parse_args(argv)
    if args.dry_run and args.apply_001_create_schema_migrations:
        parser.error("choose exactly one of --dry-run or --apply-001-create-schema-migrations")
    if not args.dry_run and not args.apply_001_create_schema_migrations:
        parser.error("refusing to run without --dry-run or --apply-001-create-schema-migrations")
    if args.apply_001_create_schema_migrations and not args.expected_database:
        parser.error("--expected-database is required for apply")
    if args.apply_001_create_schema_migrations and not args.confirm_dev_db:
        parser.error("--confirm-dev-db is required for apply")
    if args.apply_001_create_schema_migrations and not args.backup_confirmed:
        parser.error("--backup-confirmed is required for apply")

    from app.db.database import engine

    if args.dry_run:
        result = collect_dry_run_plan(engine)
    else:
        result = apply_001_create_schema_migrations(
            engine,
            backup_confirmed=args.backup_confirmed,
            dev_database_confirmed=args.confirm_dev_db,
            expected_database=args.expected_database,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.dry_run:
        return 0
    return 0 if result.get("status") in SUCCESSFUL_APPLY_STATUSES else 1


if __name__ == "__main__":
    raise SystemExit(main())
