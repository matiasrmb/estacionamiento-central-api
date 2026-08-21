"""Read-only safety checks for future schema migration apply support."""

from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from app.db.schema_inventory import collect_read_only_schema_inventory_from_engine
from app.db.schema_migration_runner import plan_schema_migrations


SCHEMA_MIGRATION_PREFLIGHT_VERSION = 1

FUTURE_APPLY_CHECKLIST = (
    "Verify a current database backup.",
    "Test restoring the backup.",
    "Complete a staging migration run.",
    "Confirm the database is not production unless explicitly approved.",
)


def evaluate_schema_migration_preflight(
    inventory: dict[str, Any],
    plan: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic safety findings without executing migration SQL."""
    context = runtime_context or {}
    database_value = inventory.get("database") or plan.get("database")
    database = str(database_value) if database_value else None
    backup_confirmed = bool(context.get("backup_confirmed", False))
    environment_value = context.get("environment")
    environment = str(environment_value) if environment_value is not None else None
    inventory_present = _schema_migrations_present(inventory)
    plan_present = _schema_migrations_present(plan)
    pending_migrations = sorted(
        str(migration.get("id"))
        for migration in plan.get("migrations", [])
        if isinstance(migration, dict) and migration.get("status") == "pending"
    )
    unknown_migrations = sorted(
        str(migration.get("id"))
        for migration in plan.get("migrations", [])
        if isinstance(migration, dict) and migration.get("status") == "unknown"
    )
    statuses = []
    statuses.append(_check("database_name", bool(database), "Database name is present."))
    statuses.append(_check(
        "schema_migrations_status",
        inventory_present is not None and plan_present is not None and inventory_present == plan_present,
        "Inventory and plan agree on schema_migrations status.",
    ))
    statuses.append(_check(
        "migration_status_known",
        not unknown_migrations,
        "All migration statuses are known.",
    ))
    statuses.append(_check(
        "backup_confirmed_for_future_apply",
        not pending_migrations or backup_confirmed,
        "A backup must be confirmed before any future apply with pending migrations.",
    ))
    statuses.append(_check(
        "apply_mode_unavailable",
        plan.get("mode") == "dry_run" and all(
            migration.get("will_execute") is False
            for migration in plan.get("migrations", [])
            if isinstance(migration, dict)
        ),
        "Apply mode is unavailable and no migration will execute in this slice.",
    ))

    has_failures = any(check["status"] == "BLOCKED" for check in statuses)
    status = "BLOCKED" if has_failures else "READY_FOR_MANUAL_REVIEW" if pending_migrations else "PREFLIGHT_OK"
    return {
        "preflight_version": SCHEMA_MIGRATION_PREFLIGHT_VERSION,
        "mode": "dry_run",
        "status": status,
        "database": database,
        "runtime_context": {
            "backup_confirmed": backup_confirmed,
            "environment": environment,
        },
        "schema_migrations": {
            "inventory_present": inventory_present,
            "plan_present": plan_present,
        },
        "pending_migrations": {
            "count": len(pending_migrations),
            "ids": pending_migrations,
        },
        "unknown_migrations": unknown_migrations,
        "apply": {
            "available": False,
            "will_execute": False,
            "destructive_actions": [],
        },
        "checks": statuses,
        "future_apply_checklist": list(FUTURE_APPLY_CHECKLIST),
    }


def collect_dry_run_preflight(engine: Any, runtime_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect inventory through the existing read-only path and evaluate it."""
    inventory = collect_read_only_schema_inventory_from_engine(engine)
    return evaluate_schema_migration_preflight(inventory, plan_schema_migrations(inventory), runtime_context)


def _schema_migrations_present(source: dict[str, Any]) -> bool | None:
    schema_migrations = source.get("schema_migrations")
    if isinstance(schema_migrations, dict) and "present" in schema_migrations:
        value = schema_migrations["present"]
        if value in (True, False, None):
            return value
    tables = source.get("tables")
    if not isinstance(tables, list):
        return None
    return any(
        isinstance(row, dict) and str(row.get("table_name", "")).casefold() == "schema_migrations"
        for row in tables
    )


def _check(name: str, passed: bool, message: str) -> dict[str, str]:
    return {"name": name, "status": "PASS" if passed else "BLOCKED", "message": message}


def main(argv: Sequence[str] | None = None) -> int:
    """Print a read-only migration preflight; apply mode is not supported."""
    parser = argparse.ArgumentParser(description="Preflight future schema migrations without applying them.")
    parser.add_argument("--dry-run", action="store_true", help="collect inventory and print read-only preflight findings")
    parser.add_argument("--backup-confirmed", action="store_true", help="record backup confirmation for future apply review")
    parser.add_argument("--environment", help="record the target environment for future apply review")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("refusing to run without --dry-run; apply mode is not implemented")

    from app.db.database import engine

    print(json.dumps(
        collect_dry_run_preflight(engine, {
            "backup_confirmed": args.backup_confirmed,
            "environment": args.environment,
        }),
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
