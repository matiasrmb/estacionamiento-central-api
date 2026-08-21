"""Dry-run planning for future schema migrations; this module never applies DDL."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Sequence

from app.db.schema_inventory import collect_read_only_schema_inventory_from_engine


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


def plan_schema_migrations(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable plan without accessing a database."""
    table_names = _table_names(inventory)
    inventory_complete = table_names is not None
    migrations = []

    for migration in MIGRATIONS:
        if migration.migration_id == "001_create_schema_migrations":
            if not inventory_complete:
                status = "unknown"
            elif "schema_migrations" in table_names:
                status = "applied"
            else:
                status = "pending"
        else:
            status = "blocked"
        migrations.append({
            "id": migration.migration_id,
            "description": migration.description,
            "status": status,
            "sql": list(migration.statements) if status == "pending" else [],
            "will_execute": False,
        })

    warnings = [
        "Dry-run only: no SQL statements were executed.",
        "Apply mode is intentionally unavailable in this slice.",
    ]
    if not inventory_complete:
        warnings.append("Inventory does not include a tables list; migration status is unknown.")

    return {
        "plan_version": SCHEMA_MIGRATION_PLAN_VERSION,
        "mode": "dry_run",
        "database": inventory.get("database"),
        "schema_migrations": {
            "present": "schema_migrations" in table_names if inventory_complete else None,
        },
        "migrations": migrations,
        "prerequisites": [
            "Review this plan and take a database backup before any future apply run.",
            "A future apply implementation must record successful migration IDs atomically.",
        ],
        "warnings": warnings,
    }


def collect_dry_run_plan(engine: Any) -> dict[str, Any]:
    """Collect read-only inventory through an engine, then build a non-mutating plan."""
    return plan_schema_migrations(collect_read_only_schema_inventory_from_engine(engine))


def _table_names(inventory: dict[str, Any]) -> set[str] | None:
    tables = inventory.get("tables")
    if not isinstance(tables, list):
        return None
    return {
        str(row.get("table_name", "")).casefold()
        for row in tables
        if isinstance(row, dict)
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Print a read-only migration plan; applying migrations is not supported."""
    parser = argparse.ArgumentParser(description="Plan future schema migrations without applying them.")
    parser.add_argument("--dry-run", action="store_true", help="collect inventory and print a non-mutating plan")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("refusing to run without --dry-run; apply mode is not implemented")

    from app.db.database import engine

    print(json.dumps(collect_dry_run_plan(engine), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
