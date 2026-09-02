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
- Historical ``005_monthly_payments.sql`` defines ``VARCHAR(40)``; managed 003
  is the authoritative corrective migration to the baseline ``VARCHAR(50)``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import text

from app.db.schema_inventory import (
    collect_read_only_schema_inventory_from_engine,
    operaciones_servicio_ingreso_generado_fk_contract,
    operaciones_servicio_contract,
    operaciones_servicio_tipo_vehiculo_lavado_fk_contract,
    ingresos_en_lavado_contract,
    lavados_contract,
    pagos_mensuales_metodo_pago_contract,
    schema_migrations_contract,
    tipos_lavado_contract,
    tipos_vehiculo_lavado_contract,
)


SCHEMA_MIGRATION_PLAN_VERSION = 1
MIGRATION_001_ID = "001_create_schema_migrations"
MIGRATION_002_ID = "002_create_tipos_lavado"
MIGRATION_003_ID = "003_widen_pagos_mensuales_metodo_pago"
MIGRATION_004_ID = "004_add_operaciones_servicio_ingreso_generado_fk"
MIGRATION_005_ID = "005_add_operaciones_servicio_tipo_vehiculo_lavado_fk"
MIGRATION_006_ID = "006_create_lavados_and_ingresos_en_lavado"
MIGRATION_007_ID = "007_migrate_wash_vehicle_type_pricing"
MIGRATION_008_ID = "008_complete_operaciones_servicio_contract"
MANAGED_MIGRATION_IDS = (MIGRATION_001_ID, MIGRATION_002_ID, MIGRATION_003_ID, MIGRATION_004_ID, MIGRATION_005_ID, MIGRATION_006_ID, MIGRATION_007_ID, MIGRATION_008_ID)
MIGRATION_RECORD_SQL = "INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"
MIGRATION_001_RECORD_SQL = MIGRATION_RECORD_SQL
MIGRATION_002_SEED_SQL = (
    "INSERT INTO tipos_lavado (codigo, nombre, activo) "
    "VALUES ('lavado_general', 'Lavado', 1) "
    "ON DUPLICATE KEY UPDATE codigo = codigo"
)
SUCCESSFUL_APPLY_STATUSES = frozenset({"applied", "noop", "repaired"})
WASH_VEHICLE_TYPE_DEFAULTS = (
    ("lavado_citycar", "CityCar", 5000), ("lavado_suv", "SUV", 8000),
    ("lavado_camioneta", "Camioneta", 10000), ("lavado_furgon", "Furgón", 15000),
    ("lavado_minibus", "Mini bus o vehículos grandes", 25000),
)


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
    MigrationMetadata(
        MIGRATION_003_ID,
        "Widen pagos_mensuales.metodo_pago while preserving its nullable, no-default contract.",
        ("ALTER TABLE pagos_mensuales MODIFY COLUMN metodo_pago VARCHAR(50) NULL",),
    ),
    MigrationMetadata(
        MIGRATION_004_ID,
        "Add the restrictive operaciones_servicio generated-ingreso foreign key.",
        ("ALTER TABLE operaciones_servicio ADD CONSTRAINT fk_operaciones_servicio_ingreso_generado FOREIGN KEY (id_ingreso_generado) REFERENCES ingresos (id_ingreso)",),
    ),
    MigrationMetadata(
        MIGRATION_005_ID,
        "Add the restrictive operaciones_servicio wash-vehicle-type foreign key and its child index.",
        (
            "ALTER TABLE operaciones_servicio\n"
            "    ADD INDEX idx_operaciones_servicio_tipo_vehiculo_lavado (id_tipo_vehiculo_lavado),\n"
            "    ADD CONSTRAINT fk_operaciones_servicio_tipo_vehiculo_lavado\n"
            "        FOREIGN KEY (id_tipo_vehiculo_lavado)\n"
            "        REFERENCES tipos_vehiculo_lavado (id_tipo_vehiculo_lavado)",
        ),
    ),
    MigrationMetadata(
        MIGRATION_006_ID,
        "Create or safely complete lavados and add the nullable ingresos wash flag.",
        (
            "CREATE TABLE lavados (\n"
            "    id_lavado INT AUTO_INCREMENT PRIMARY KEY,\n"
            "    id_ingreso INT NOT NULL,\n"
            "    id_vehiculo INT NOT NULL,\n"
            "    patente VARCHAR(10) NOT NULL,\n"
            "    categoria_lavado VARCHAR(50) NOT NULL,\n"
            "    valor_lavado INT NOT NULL,\n"
            "    id_tipo_vehiculo_lavado INT NULL,\n"
            "    tipo_vehiculo_lavado_snapshot VARCHAR(80) DEFAULT NULL,\n"
            "    fecha_hora_inicio DATETIME NOT NULL,\n"
            "    fecha_hora_fin DATETIME DEFAULT NULL,\n"
            "    usuario_inicio VARCHAR(50) NOT NULL,\n"
            "    usuario_fin VARCHAR(50) DEFAULT NULL,\n"
            "    estado ENUM('activo', 'finalizado') NOT NULL DEFAULT 'activo',\n"
            "    CONSTRAINT fk_lavados_ingreso FOREIGN KEY (id_ingreso) REFERENCES ingresos (id_ingreso),\n"
            "    CONSTRAINT fk_lavados_vehiculo FOREIGN KEY (id_vehiculo) REFERENCES vehiculos (id_vehiculo),\n"
            "    CONSTRAINT fk_lavados_tipo_vehiculo_lavado FOREIGN KEY (id_tipo_vehiculo_lavado) REFERENCES tipos_vehiculo_lavado (id_tipo_vehiculo_lavado)\n"
            ")",
        ),
    ),
    MigrationMetadata(
        MIGRATION_007_ID,
        "Migrate managed wash vehicle pricing from the legacy table and configuration.",
        (
            "CREATE TABLE tipos_vehiculo_lavado (\n"
            "    id_tipo_vehiculo_lavado INT AUTO_INCREMENT PRIMARY KEY,\n"
            "    codigo VARCHAR(50) NOT NULL UNIQUE,\n"
            "    nombre VARCHAR(80) NOT NULL,\n"
            "    valor_lavado INT NOT NULL,\n"
            "    activo TINYINT(1) NOT NULL DEFAULT 1,\n"
            "    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,\n"
            "    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP\n"
            ")",
        ),
    ),
    MigrationMetadata(
        MIGRATION_008_ID,
        "Complete the existing operaciones_servicio runtime contract without creating it or changing data.",
        (),
    ),
)


def plan_schema_migrations(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable plan without accessing a database."""
    table_names = _table_names(inventory)
    complete = table_names is not None
    statuses = {
        MIGRATION_001_ID: _migration_001_status(inventory, table_names, complete),
        MIGRATION_002_ID: _migration_002_status(inventory, table_names, complete),
        MIGRATION_003_ID: _migration_003_status(inventory, table_names, complete),
        MIGRATION_004_ID: _migration_004_status(inventory, table_names, complete),
        MIGRATION_005_ID: _migration_005_status(inventory, table_names, complete),
        MIGRATION_006_ID: _migration_006_status(inventory, table_names, complete),
        MIGRATION_007_ID: _migration_007_status(inventory, table_names, complete),
        MIGRATION_008_ID: _migration_008_status(inventory, table_names, complete),
    }
    migrations = [
        {
            "id": migration.migration_id,
            "description": migration.description,
            "status": statuses[migration.migration_id],
            "sql": _planned_006_sql(inventory, statuses[migration.migration_id]) if migration.migration_id == MIGRATION_006_ID else _planned_007_sql(inventory, statuses[migration.migration_id]) if migration.migration_id == MIGRATION_007_ID else _planned_008_sql(inventory, statuses[migration.migration_id]) if migration.migration_id == MIGRATION_008_ID else _planned_sql(migration, statuses[migration.migration_id], table_names),
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
        "pagos_mensuales_metodo_pago": pagos_mensuales_metodo_pago_contract(inventory),
        "operaciones_servicio_ingreso_generado_fk": operaciones_servicio_ingreso_generado_fk_contract(inventory),
        "operaciones_servicio_tipo_vehiculo_lavado_fk": operaciones_servicio_tipo_vehiculo_lavado_fk_contract(inventory),
        "operaciones_servicio": operaciones_servicio_contract(inventory),
        "lavados": lavados_contract(inventory),
        "ingresos_en_lavado": ingresos_en_lavado_contract(inventory),
        "tipos_vehiculo_lavado": tipos_vehiculo_lavado_contract(inventory),
        "wash_vehicle_type_pricing": {
            "canonical": tipos_vehiculo_lavado_contract(inventory),
            "legacy_plural": tipos_vehiculo_lavado_contract(inventory, "tipos_vehiculos_lavado"),
            "issues": _wash_pricing_issues(inventory),
            "source_data": _wash_pricing_source_data(inventory),
        },
        "migrations": migrations,
        "prerequisites": [
            "Review this plan and take a database backup before any future apply run.",
            "Apply validates the expected database name before executing migration SQL.",
        ],
        "warnings": warnings,
    }


def collect_dry_run_plan(engine: Any, runtime_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect one read-only inventory and attach its canonical apply preflight."""
    from app.db.schema_migration_preflight import evaluate_schema_migration_preflight

    inventory = collect_read_only_schema_inventory_from_engine(engine)
    plan = plan_schema_migrations(inventory)
    plan["preflight"] = evaluate_schema_migration_preflight(inventory, plan, runtime_context)
    return plan


def apply_001_create_schema_migrations(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only migration 001 after read-only inventory and preflight checks."""
    return _apply(engine, MIGRATION_001_ID, **kwargs)


def apply_002_create_tipos_lavado(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only migration 002 without overwriting mutable seed values."""
    return _apply(engine, MIGRATION_002_ID, **kwargs)


def apply_003_widen_pagos_mensuales_metodo_pago(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only the controlled monthly-payment method widen."""
    return _apply(engine, MIGRATION_003_ID, **kwargs)


def apply_004_add_operaciones_servicio_ingreso_generado_fk(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only the controlled generated-ingreso foreign key."""
    return _apply(engine, MIGRATION_004_ID, **kwargs)


def apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only the controlled wash-vehicle-type foreign key and index."""
    return _apply(engine, MIGRATION_005_ID, **kwargs)


def apply_006_create_lavados_and_ingresos_en_lavado(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only the managed lavados and ingresos.en_lavado migration."""
    return _apply(engine, MIGRATION_006_ID, **kwargs)


def apply_007_migrate_wash_vehicle_type_pricing(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only the managed wash vehicle pricing migration."""
    return _apply(engine, MIGRATION_007_ID, **kwargs)


def apply_008_complete_operaciones_servicio_contract(engine: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply only additive completion of the existing service-operation table."""
    return _apply(engine, MIGRATION_008_ID, **kwargs)


def _apply(
    engine: Any, migration_id: str, *, backup_confirmed: bool, dev_database_confirmed: bool,
    expected_database: str | None = None,
    profile: str | None = None,
    environment: str | None = None,
    backup_path: str | None = None,
    preflight_sha256: str | None = None,
) -> dict[str, Any]:
    from app.db.schema_migration_preflight import evaluate_schema_migration_preflight

    inventory = collect_read_only_schema_inventory_from_engine(engine)
    plan = plan_schema_migrations(inventory)
    preflight = evaluate_schema_migration_preflight(inventory, plan, {
        # Production applies compare this new read-only snapshot to the
        # installer preflight before any write is permitted.
        "apply_requested": False,
        "backup_confirmed": backup_confirmed,
        "dev_database_confirmed": dev_database_confirmed,
        "expected_database": expected_database,
        "profile": profile,
        "environment": environment,
    })
    migration = next(item for item in plan["migrations"] if item["id"] == migration_id)
    if profile == "installer-production":
        if not _production_apply_confirmed(
            environment, backup_confirmed, backup_path, preflight_sha256, preflight,
        ):
            return _result(migration_id, "refused", [], ["Production confirmation requirements are not satisfied; no SQL was executed."], preflight)
    elif not dev_database_confirmed:
        return _result(migration_id, "refused", [], ["Development database confirmation is required; no SQL was executed."], preflight)
    if not expected_database or inventory.get("database") != expected_database:
        return _result(migration_id, "refused", [], ["Expected database does not match the active database; no SQL was executed."], preflight)
    if migration["status"] == "applied":
        return _result(migration_id, "noop", [], [f"Migration {migration_id[:3]} is already recorded; no SQL was executed."], preflight)
    if migration["status"] == "invalid_contract":
        return _result(migration_id, "invalid_contract", [], ["The existing table does not match the required contract; no SQL was executed."], preflight)
    if migration["status"] in {"unknown", "blocked_prerequisite", "inconsistent_state"}:
        return _result(migration_id, "refused", [], ["Migration prerequisites are not satisfied; no SQL was executed."], preflight)
    if any(
        check["status"] == "BLOCKED" and check["name"] != "migration_prerequisites"
        for check in preflight["checks"]
    ):
        return _result(migration_id, "refused", [], ["Preflight is BLOCKED; no SQL was executed."], preflight)
    if migration_id == MIGRATION_001_ID:
        return _apply_001(engine, migration["status"], preflight)
    if migration_id == MIGRATION_002_ID:
        return _apply_002(engine, migration["status"], _table_names(inventory) or set(), preflight)
    if migration_id == MIGRATION_003_ID:
        return _apply_003(engine, migration["status"], preflight)
    if migration_id == MIGRATION_004_ID:
        return _apply_004(engine, migration["status"], preflight)
    if migration_id == MIGRATION_005_ID:
        return _apply_005(engine, migration["status"], preflight)
    if migration_id == MIGRATION_007_ID:
        return _apply_007(engine, migration["status"], migration["sql"], preflight)
    if migration_id == MIGRATION_008_ID:
        return _apply_008(engine, migration["status"], migration["sql"], preflight)
    return _apply_006(engine, migration["status"], migration["sql"], preflight)


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
            except Exception:
                return _result(
                    MIGRATION_001_ID, "failed_after_create", ["CREATE TABLE"],
                    ["CREATE TABLE succeeded, but the migration record INSERT failed.", "Retry will record migration 001 after a fresh inventory."], preflight,
                )
    except Exception:
        return _result(MIGRATION_001_ID, "failed", [], ["Migration 001 failed; no connection details are reported."], preflight)
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
    except Exception:
        status = "failed_after_create" if executed == ["CREATE TABLE"] else "failed_after_seed" if "INSERT seed" in executed else "failed"
        return _result(MIGRATION_002_ID, status, executed, ["Migration 002 failed; no connection details are reported."], preflight)
    return _result(MIGRATION_002_ID, "applied", executed, [], preflight)


def _apply_003(engine: Any, status: str, preflight: dict[str, Any]) -> dict[str, Any]:
    if status == "repair_required":
        return _record(engine, MIGRATION_003_ID, "repaired", [], preflight)
    if status != "pending":
        return _result(MIGRATION_003_ID, "refused", [], ["Migration is not pending; no SQL was executed."], preflight)
    executed: list[str] = []
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATIONS[2].statements[0]))
            executed.append("ALTER TABLE")
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": MIGRATION_003_ID})
            executed.append("INSERT migration record")
    except Exception:
        status = "failed_after_alter" if executed == ["ALTER TABLE"] else "failed"
        return _result(MIGRATION_003_ID, status, executed, ["Migration 003 failed; no connection details are reported."], preflight)
    return _result(MIGRATION_003_ID, "applied", executed, [], preflight)


def _apply_004(engine: Any, status: str, preflight: dict[str, Any]) -> dict[str, Any]:
    if status == "repair_required":
        return _record(engine, MIGRATION_004_ID, "repaired", [], preflight)
    if status != "pending":
        return _result(MIGRATION_004_ID, "refused", [], ["Migration is not pending; no SQL was executed."], preflight)
    executed: list[str] = []
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATIONS[3].statements[0]))
            executed.append("ALTER TABLE")
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": MIGRATION_004_ID})
    except Exception:
        if executed:
            return _result(
                MIGRATION_004_ID, "failed_after_alter", executed,
                [
                    "ALTER TABLE succeeded, but the migration record INSERT failed; MySQL DDL may already be committed.",
                    "Retry may record migration 004 only if a fresh inventory sees the valid FK.",
                ], preflight,
            )
        return _result(MIGRATION_004_ID, "failed", [], ["Migration 004 failed; no connection details are reported."], preflight)
    return _result(MIGRATION_004_ID, "applied", ["ALTER TABLE", "INSERT migration record"], [], preflight)


def _apply_005(engine: Any, status: str, preflight: dict[str, Any]) -> dict[str, Any]:
    if status == "repair_required":
        return _record(engine, MIGRATION_005_ID, "repaired", [], preflight)
    if status != "pending":
        return _result(MIGRATION_005_ID, "refused", [], ["Migration is not pending; no SQL was executed."], preflight)
    executed: list[str] = []
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATIONS[4].statements[0]))
            executed.append("ALTER TABLE")
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": MIGRATION_005_ID})
    except Exception:
        if executed:
            return _result(
                MIGRATION_005_ID, "failed_after_alter", executed,
                [
                    "ALTER TABLE succeeded, but the migration record INSERT failed; MySQL DDL may already be committed.",
                    "Retry may record migration 005 only if a fresh inventory sees the valid index and FK.",
                ], preflight,
            )
        return _result(MIGRATION_005_ID, "failed", [], ["Migration 005 failed; no connection details are reported."], preflight)
    return _result(MIGRATION_005_ID, "applied", ["ALTER TABLE", "INSERT migration record"], [], preflight)


def _apply_006(engine: Any, status: str, statements: list[str], preflight: dict[str, Any]) -> dict[str, Any]:
    if status == "repair_required":
        return _record(engine, MIGRATION_006_ID, "repaired", [], preflight)
    if status != "pending":
        return _result(MIGRATION_006_ID, "refused", [], ["Migration is not pending; no SQL was executed."], preflight)
    executed: list[str] = []
    try:
        with engine.begin() as conn:
            for statement in statements[:-1]:
                conn.execute(text(statement))
                executed.append("CREATE TABLE" if statement.startswith("CREATE TABLE") else "ALTER TABLE")
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": MIGRATION_006_ID})
            executed.append("INSERT migration record")
    except Exception:
        if executed:
            return _result(MIGRATION_006_ID, "failed_after_ddl", executed, ["DDL may already be committed; retry only after a fresh inventory validates the target contract.", "Migration 006 failed; no connection details are reported."], preflight)
        return _result(MIGRATION_006_ID, "failed", [], ["Migration 006 failed; no connection details are reported."], preflight)
    return _result(MIGRATION_006_ID, "applied", executed, [], preflight)


def _apply_007(engine: Any, status: str, statements: list[str], preflight: dict[str, Any]) -> dict[str, Any]:
    if status == "repair_required":
        return _record(engine, MIGRATION_007_ID, "repaired", [], preflight)
    if status != "pending":
        return _result(MIGRATION_007_ID, "refused", [], ["Migration is not pending; no SQL was executed."], preflight)
    executed: list[str] = []
    try:
        with engine.begin() as conn:
            for statement in statements[:-1]:
                conn.execute(text(statement))
                executed.append(_statement_type(statement))
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": MIGRATION_007_ID})
            executed.append("INSERT migration record")
    except Exception:
        return _result(MIGRATION_007_ID, "failed_after_migration" if executed else "failed", executed, ["Migration 007 failed; no connection details are reported."], preflight)
    return _result(MIGRATION_007_ID, "applied", executed, [], preflight)


def _apply_008(engine: Any, status: str, statements: list[str], preflight: dict[str, Any]) -> dict[str, Any]:
    if status == "repair_required":
        return _record(engine, MIGRATION_008_ID, "repaired", [], preflight)
    if status != "pending":
        return _result(MIGRATION_008_ID, "refused", [], ["Migration is not pending; no SQL was executed."], preflight)
    executed = []
    try:
        with engine.begin() as conn:
            for statement in statements[:-1]:
                conn.execute(text(statement))
                executed.append("ALTER TABLE")
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": MIGRATION_008_ID})
            executed.append("INSERT migration record")
    except Exception:
        return _result(MIGRATION_008_ID, "failed_after_alter" if executed else "failed", executed, ["Migration 008 failed; retry only after a fresh inventory validates the full contract."], preflight)
    return _result(MIGRATION_008_ID, "applied", executed, [], preflight)


def _record(engine: Any, migration_id: str, status: str, executed: list[str], preflight: dict[str, Any]) -> dict[str, Any]:
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATION_RECORD_SQL), {"migration_id": migration_id})
    except Exception:
        return _result(migration_id, "failed", executed, ["Migration record INSERT failed; no connection details are reported."], preflight)
    statement_type = "INSERT" if migration_id == MIGRATION_001_ID else "INSERT migration record"
    return _result(migration_id, status, [*executed, statement_type], [], preflight)


def _result(migration_id: str, status: str, executed: list[str], warnings: list[str], preflight: dict[str, Any]) -> dict[str, Any]:
    return {"migration_id": migration_id, "status": status, "executed_statements_count": len(executed), "executed_statement_types": executed, "warnings": warnings, "preflight": preflight}


def _production_apply_confirmed(
    environment: str | None,
    backup_confirmed: bool,
    backup_path: str | None,
    preflight_sha256: str | None,
    preflight: dict[str, Any],
) -> bool:
    return (
        environment == "production"
        and backup_confirmed
        and _is_nonempty_backup(backup_path)
        and bool(preflight_sha256)
        and preflight_sha256 == preflight.get("canonical_sha256")
    )


def _is_nonempty_backup(backup_path: str | None) -> bool:
    if not backup_path:
        return False
    path = Path(backup_path)
    return path.is_file() and path.stat().st_size > 0


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


def _migration_003_status(inventory: dict[str, Any], tables: set[str] | None, complete: bool) -> str:
    if not complete:
        return "unknown"
    if _migration_recorded(inventory, MIGRATION_001_ID) is not True or _migration_recorded(inventory, MIGRATION_002_ID) is not True:
        return "blocked_prerequisite"
    contract = pagos_mensuales_metodo_pago_contract(inventory)
    recorded = _migration_recorded(inventory, MIGRATION_003_ID)
    if recorded is True:
        if contract["valid"] is True:
            return "applied"
        if contract["state"] in {"missing_table", "missing_column", "widen_safe"}:
            return "inconsistent_state"
        return "invalid_contract"
    if contract["valid"] is True:
        return "repair_required"
    if contract["widen_safe"] is True:
        return "pending"
    return "invalid_contract"


def _migration_004_status(inventory: dict[str, Any], tables: set[str] | None, complete: bool) -> str:
    if not complete:
        return "unknown"
    if any(_migration_recorded(inventory, migration_id) is not True for migration_id in (MIGRATION_001_ID, MIGRATION_002_ID, MIGRATION_003_ID)):
        return "blocked_prerequisite"
    contract = operaciones_servicio_ingreso_generado_fk_contract(inventory)
    recorded = _migration_recorded(inventory, MIGRATION_004_ID)
    if recorded is True:
        if contract["valid"] is True:
            return "applied"
        return "inconsistent_state" if contract["state"] in {"safe_to_add", "blocked_orphans", "unknown"} else "invalid_contract"
    if contract["valid"] is True:
        return "repair_required"
    if contract["add_safe"] is True:
        return "pending"
    return "blocked_prerequisite" if contract["state"] == "blocked_orphans" else "invalid_contract" if contract["state"] == "invalid" else "unknown"


def _migration_005_status(inventory: dict[str, Any], tables: set[str] | None, complete: bool) -> str:
    if not complete:
        return "unknown"
    if any(_migration_recorded(inventory, migration_id) is not True for migration_id in (MIGRATION_001_ID, MIGRATION_002_ID, MIGRATION_003_ID, MIGRATION_004_ID)):
        return "blocked_prerequisite"
    contract = operaciones_servicio_tipo_vehiculo_lavado_fk_contract(inventory)
    if any(issue.endswith("table is missing") or issue.endswith("column is missing") for issue in contract["issues"]):
        return "blocked_prerequisite"
    recorded = _migration_recorded(inventory, MIGRATION_005_ID)
    if recorded is True:
        if contract["valid"] is True:
            return "applied"
        return "inconsistent_state" if contract["state"] in {"safe_to_add", "blocked_orphans", "unknown"} else "invalid_contract"
    if contract["valid"] is True:
        return "repair_required"
    if contract["add_safe"] is True:
        return "pending"
    return "blocked_prerequisite" if contract["state"] == "blocked_orphans" else "invalid_contract" if contract["state"] in {"invalid", "name_collision"} else "unknown"


def _migration_006_status(inventory: dict[str, Any], tables: set[str] | None, complete: bool) -> str:
    if not complete:
        return "unknown"
    if any(_migration_recorded(inventory, migration_id) is not True for migration_id in MANAGED_MIGRATION_IDS[:5]):
        return "blocked_prerequisite"
    lavados = lavados_contract(inventory)
    en_lavado = ingresos_en_lavado_contract(inventory)
    recorded = _migration_recorded(inventory, MIGRATION_006_ID)
    if lavados["state"] == "invalid" and any(issue.endswith("table is missing") for issue in lavados["issues"]):
        return "blocked_prerequisite"
    if lavados["state"] == "invalid" or en_lavado["state"] == "invalid":
        return "invalid_contract"
    if recorded is True:
        return "applied" if lavados["valid"] and en_lavado["valid"] else "inconsistent_state"
    if lavados["valid"] and en_lavado["valid"]:
        return "repair_required"
    if lavados["state"] in {"safe_to_create", "safe_to_upgrade"} and en_lavado["state"] in {"valid", "safe_to_add"}:
        return "pending"
    return "unknown"


def _migration_007_status(inventory: dict[str, Any], tables: set[str] | None, complete: bool) -> str:
    if not complete:
        return "unknown"
    if any(_migration_recorded(inventory, migration_id) is not True for migration_id in MANAGED_MIGRATION_IDS[:6]):
        return "blocked_prerequisite"
    canonical = tipos_vehiculo_lavado_contract(inventory)
    plural = tipos_vehiculo_lavado_contract(inventory, "tipos_vehiculos_lavado")
    if canonical["valid"] is False or plural["valid"] is False or _wash_pricing_issues(inventory):
        return "invalid_contract"
    recorded = _migration_recorded(inventory, MIGRATION_007_ID)
    data_valid = _wash_pricing_known_codes_present(inventory)
    if recorded is True:
        return "applied" if canonical["valid"] is True and data_valid else "inconsistent_state"
    if canonical["valid"] is True and data_valid:
        return "repair_required"
    return "pending"


def _migration_008_status(inventory: dict[str, Any], tables: set[str] | None, complete: bool) -> str:
    if not complete:
        return "unknown"
    if any(_migration_recorded(inventory, migration_id) is not True for migration_id in MANAGED_MIGRATION_IDS[:7]):
        return "blocked_prerequisite"
    contract = operaciones_servicio_contract(inventory)
    recorded = _migration_recorded(inventory, MIGRATION_008_ID)
    if contract["state"] == "blocked_prerequisite":
        return "blocked_prerequisite"
    if contract["valid"] is True:
        return "applied" if recorded else "repair_required"
    if contract["add_safe"] is True:
        return "inconsistent_state" if recorded else "pending"
    return "invalid_contract"


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
    if migration.migration_id in {MIGRATION_003_ID, MIGRATION_004_ID, MIGRATION_005_ID}:
        return [*migration.statements, MIGRATION_RECORD_SQL]
    return list(migration.statements)


def _planned_006_sql(inventory: dict[str, Any], status: str) -> list[str]:
    if status == "repair_required":
        return [MIGRATION_RECORD_SQL]
    if status != "pending":
        return []
    statements = []
    lavados = lavados_contract(inventory)
    if lavados["state"] == "safe_to_create":
        statements.append(MIGRATIONS[5].statements[0])
    elif lavados["state"] == "safe_to_upgrade":
        columns = {str(row.get("column_name", "")).casefold() for row in inventory.get("columns", []) if isinstance(row, dict) and str(row.get("table_name", "")).casefold() == "lavados"}
        clauses = []
        if "id_tipo_vehiculo_lavado" not in columns:
            clauses.append("ADD COLUMN id_tipo_vehiculo_lavado INT NULL")
        if "tipo_vehiculo_lavado_snapshot" not in columns:
            clauses.append("ADD COLUMN tipo_vehiculo_lavado_snapshot VARCHAR(80) DEFAULT NULL")
        for suffix, child, parent_table, parent in (
            ("ingreso", "id_ingreso", "ingresos", "id_ingreso"),
            ("vehiculo", "id_vehiculo", "vehiculos", "id_vehiculo"),
            ("tipo_vehiculo_lavado", "id_tipo_vehiculo_lavado", "tipos_vehiculo_lavado", "id_tipo_vehiculo_lavado"),
        ):
            if suffix in lavados["missing_foreign_keys"]:
                clauses.append(f"ADD CONSTRAINT fk_lavados_{suffix} FOREIGN KEY ({child}) REFERENCES {parent_table} ({parent})")
        statements.append("ALTER TABLE lavados\n    " + ",\n    ".join(clauses))
    if ingresos_en_lavado_contract(inventory)["state"] == "safe_to_add":
        statements.append("ALTER TABLE ingresos ADD COLUMN en_lavado TINYINT(1) DEFAULT 0")
    return [*statements, MIGRATION_RECORD_SQL]


def _planned_007_sql(inventory: dict[str, Any], status: str) -> list[str]:
    if status == "repair_required":
        return [MIGRATION_RECORD_SQL]
    if status != "pending":
        return []
    tables = _table_names(inventory) or set()
    canonical_exists = "tipos_vehiculo_lavado" in tables
    statements = [] if canonical_exists else [MIGRATIONS[6].statements[0]]
    if not canonical_exists and "tipos_vehiculos_lavado" in tables:
        statements.append("INSERT INTO tipos_vehiculo_lavado (codigo, nombre, valor_lavado, activo) SELECT codigo, nombre, valor_lavado, activo FROM tipos_vehiculos_lavado ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), valor_lavado = VALUES(valor_lavado), activo = VALUES(activo)")
    present = _wash_pricing_codes(inventory)
    for codigo, nombre, default in WASH_VEHICLE_TYPE_DEFAULTS:
        if canonical_exists and codigo in present:
            continue
        amount = _wash_pricing_config_values(inventory).get(codigo, default)
        statement = f"INSERT INTO tipos_vehiculo_lavado (codigo, nombre, valor_lavado, activo) VALUES ('{codigo}', '{nombre}', {amount}, 1)"
        statements.append(statement + (" ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), valor_lavado = VALUES(valor_lavado), activo = VALUES(activo)" if not canonical_exists else ""))
    return [*statements, MIGRATION_RECORD_SQL]


def _planned_008_sql(inventory: dict[str, Any], status: str) -> list[str]:
    if status == "repair_required":
        return [MIGRATION_RECORD_SQL]
    if status != "pending":
        return []
    contract = operaciones_servicio_contract(inventory)
    column_sql = {
        "tipo_vehiculo_lavado_snapshot": "ADD COLUMN tipo_vehiculo_lavado_snapshot VARCHAR(80) NULL",
        "valor_lavado_snapshot": "ADD COLUMN valor_lavado_snapshot INT NOT NULL DEFAULT 0",
        "fecha_hora_fin": "ADD COLUMN fecha_hora_fin DATETIME NULL",
        "duracion_minutos": "ADD COLUMN duracion_minutos INT NOT NULL DEFAULT 0",
        "usuario_fin": "ADD COLUMN usuario_fin VARCHAR(50) NULL",
        "estado": "ADD COLUMN estado ENUM('ACTIVO', 'FINALIZADO_COBRADO', 'CONVERTIDO_ESTADIA') NOT NULL DEFAULT 'ACTIVO'",
        "cerrado": "ADD COLUMN cerrado TINYINT(1) NOT NULL DEFAULT 0",
        "created_at": "ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
    }
    index_sql = {
        "idx_operaciones_servicio_estado_fecha": "ADD INDEX idx_operaciones_servicio_estado_fecha (estado, fecha_hora_inicio)",
        "idx_operaciones_servicio_patente": "ADD INDEX idx_operaciones_servicio_patente (patente)",
        "idx_operaciones_servicio_cierre": "ADD INDEX idx_operaciones_servicio_cierre (cerrado, estado, fecha_hora_fin)",
    }
    clauses = [column_sql[name] for name in contract["missing_columns"]]
    clauses.extend(index_sql[name] for name in contract["missing_indexes"] if name in index_sql)
    return ["ALTER TABLE operaciones_servicio\n    " + ",\n    ".join(clauses), MIGRATION_RECORD_SQL]


def _wash_pricing_config_values(inventory: dict[str, Any]) -> dict[str, int]:
    snapshot = inventory.get("config_seed_snapshot", {})
    values = snapshot.get("values", []) if isinstance(snapshot, dict) and snapshot.get("available") else []
    return {
        code: amount
        for row in values
        if isinstance(row, dict)
        for code in (_normalise_wash_code(row.get("clave")),)
        if code in _wash_pricing_default_codes()
        for amount in (_positive_int(row.get("valor")),)
        if amount is not None
    }


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str) or not re.fullmatch(r"[+]?\d+", value.strip()):
        return None
    amount = int(value.strip())
    return amount if amount > 0 else None


def _wash_pricing_issues(inventory: dict[str, Any]) -> list[str]:
    issues = []
    for table_name, snapshot in inventory.get("wash_vehicle_type_snapshots", {}).items():
        records = snapshot.get("records", []) if isinstance(snapshot, dict) else []
        codes = [_normalise_wash_code(row.get("codigo")) for row in records if isinstance(row, dict)]
        if len(codes) != len(set(codes)):
            issues.append(f"{table_name} has duplicate or ambiguous codes")
    snapshot = inventory.get("config_seed_snapshot", {})
    values = snapshot.get("values", []) if isinstance(snapshot, dict) and snapshot.get("available") else []
    known_codes = []
    for row in values:
        if not isinstance(row, dict):
            continue
        code = _normalise_wash_code(row.get("clave"))
        if code not in _wash_pricing_default_codes():
            continue
        known_codes.append(code)
        if _positive_int(row.get("valor")) is None:
            issues.append(f"configuracion.{row.get('clave')} must be a positive integer")
    if len(known_codes) != len(set(known_codes)):
        issues.append("configuracion has duplicate or ambiguous wash pricing codes")
    return issues


def _wash_pricing_codes(inventory: dict[str, Any]) -> set[str]:
    snapshot = inventory.get("wash_vehicle_type_snapshots", {}).get("tipos_vehiculo_lavado", {})
    return {_normalise_wash_code(row.get("codigo")) for row in snapshot.get("records", []) if isinstance(row, dict)} if isinstance(snapshot, dict) else set()


def _wash_pricing_known_codes_present(inventory: dict[str, Any]) -> bool:
    return _wash_pricing_default_codes().issubset(_wash_pricing_codes(inventory))


def _wash_pricing_default_codes() -> set[str]:
    return {item[0] for item in WASH_VEHICLE_TYPE_DEFAULTS}


def _normalise_wash_code(value: Any) -> str:
    """Match the case/accent/space-insensitive behavior expected from MySQL's default collation."""
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold().strip()
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _wash_pricing_source_data(inventory: dict[str, Any]) -> dict[str, Any]:
    """Return stable snapshots for every 007 input that can change a write."""
    snapshots = inventory.get("wash_vehicle_type_snapshots", {})
    values = inventory.get("config_seed_snapshot", {})
    return {
        "configuracion": {
            "available": isinstance(values, dict) and values.get("available") is True,
            "values": _canonical_source_rows(
                values.get("values", []) if isinstance(values, dict) else [], ("clave", "valor")
            ),
        },
        "tipos_vehiculo_lavado": _wash_pricing_table_source(snapshots, "tipos_vehiculo_lavado"),
        "tipos_vehiculos_lavado": _wash_pricing_table_source(snapshots, "tipos_vehiculos_lavado"),
    }


def _wash_pricing_table_source(snapshots: Any, table_name: str) -> dict[str, Any]:
    snapshot = snapshots.get(table_name, {}) if isinstance(snapshots, dict) else {}
    return {
        "available": isinstance(snapshot, dict) and snapshot.get("available") is True,
        "records": _canonical_source_rows(
            snapshot.get("records", []) if isinstance(snapshot, dict) else [],
            ("codigo", "nombre", "valor_lavado", "activo"),
        ),
    }


def _canonical_source_rows(rows: Any, fields: tuple[str, ...]) -> list[dict[str, str | None]]:
    canonical = [
        {field: None if row.get(field) is None else str(row.get(field)) for field in fields}
        for row in rows if isinstance(row, dict)
    ] if isinstance(rows, list) else []
    return sorted(canonical, key=lambda row: tuple(row[field] or "" for field in fields))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan migrations or explicitly apply one migration.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-001-create-schema-migrations", action="store_true")
    parser.add_argument("--apply-002-create-tipos-lavado", action="store_true")
    parser.add_argument("--apply-003-widen-pagos-mensuales-metodo-pago", action="store_true")
    parser.add_argument("--apply-004-add-operaciones-servicio-ingreso-generado-fk", action="store_true")
    parser.add_argument("--apply-005-add-operaciones-servicio-tipo-vehiculo-lavado-fk", action="store_true")
    parser.add_argument("--apply-006-create-lavados-and-ingresos-en-lavado", action="store_true")
    parser.add_argument("--apply-007-migrate-wash-vehicle-type-pricing", action="store_true")
    parser.add_argument("--apply-008-complete-operaciones-servicio-contract", action="store_true")
    parser.add_argument("--confirm-dev-db", action="store_true")
    parser.add_argument("--profile", choices=("installer-production",))
    parser.add_argument("--environment")
    parser.add_argument("--backup-confirmed", action="store_true")
    parser.add_argument("--backup-path")
    parser.add_argument("--preflight-sha256")
    parser.add_argument("--expected-database")
    args = parser.parse_args(argv)
    apply_flags = [args.apply_001_create_schema_migrations, args.apply_002_create_tipos_lavado, args.apply_003_widen_pagos_mensuales_metodo_pago, args.apply_004_add_operaciones_servicio_ingreso_generado_fk, args.apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk, args.apply_006_create_lavados_and_ingresos_en_lavado, args.apply_007_migrate_wash_vehicle_type_pricing, args.apply_008_complete_operaciones_servicio_contract]
    if args.dry_run and any(apply_flags) or sum(apply_flags) > 1:
        parser.error("choose exactly one of --dry-run or one explicit apply flag")
    if not args.dry_run and not any(apply_flags):
        parser.error("refusing to run without --dry-run or --apply explicit migration flag")
    if any(apply_flags) and not args.expected_database:
        parser.error("--expected-database is required for apply")
    installer_production = args.profile == "installer-production"
    if any(apply_flags) and installer_production and args.confirm_dev_db:
        parser.error("--confirm-dev-db cannot be used with --profile installer-production")
    if any(apply_flags) and installer_production:
        if args.environment != "production":
            parser.error("--environment production is required with --profile installer-production")
        if not args.backup_confirmed:
            parser.error("--backup-confirmed is required for installer-production apply")
        if not _is_nonempty_backup(args.backup_path):
            parser.error("--backup-path must identify an existing non-empty backup file for installer-production apply")
        if not args.preflight_sha256:
            parser.error("--preflight-sha256 is required for installer-production apply")
    elif any(apply_flags) and not args.confirm_dev_db:
        parser.error("--confirm-dev-db is required for apply outside installer-production")
    if any(apply_flags) and not args.backup_confirmed:
        parser.error("--backup-confirmed is required for apply")
    try:
        from app.db.database import engine
        if args.dry_run:
            result = collect_dry_run_plan(engine, {
                "backup_confirmed": args.backup_confirmed,
                "expected_database": args.expected_database,
                "profile": args.profile,
                "environment": args.environment,
            })
        else:
            apply = (
                apply_001_create_schema_migrations if args.apply_001_create_schema_migrations
                else apply_002_create_tipos_lavado if args.apply_002_create_tipos_lavado
                else apply_003_widen_pagos_mensuales_metodo_pago if args.apply_003_widen_pagos_mensuales_metodo_pago
                else apply_004_add_operaciones_servicio_ingreso_generado_fk if args.apply_004_add_operaciones_servicio_ingreso_generado_fk
                else apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk if args.apply_005_add_operaciones_servicio_tipo_vehiculo_lavado_fk
                else apply_006_create_lavados_and_ingresos_en_lavado if args.apply_006_create_lavados_and_ingresos_en_lavado
                else apply_007_migrate_wash_vehicle_type_pricing if args.apply_007_migrate_wash_vehicle_type_pricing
                else apply_008_complete_operaciones_servicio_contract
            )
            apply_kwargs = {
                "backup_confirmed": args.backup_confirmed,
                "dev_database_confirmed": args.confirm_dev_db,
                "expected_database": args.expected_database,
            }
            if installer_production:
                apply_kwargs.update({
                    "profile": args.profile,
                    "environment": args.environment,
                    "backup_path": args.backup_path,
                    "preflight_sha256": args.preflight_sha256,
                })
            result = apply(engine, **apply_kwargs)
    except Exception:
        print("Schema migration inventory could not be collected; no SQL was executed.", file=sys.stderr)
        return 1
    print(json.dumps(_safe_cli_output(result), indent=2, sort_keys=True))
    return 0 if args.dry_run or result.get("status") in SUCCESSFUL_APPLY_STATUSES else 1


def _safe_cli_output(result: dict[str, Any]) -> dict[str, Any]:
    """Avoid emitting planned SQL or driver exception details in executable output."""
    if result.get("mode") != "dry_run":
        return result
    safe = {**result}
    preflight = result.get("preflight")
    if isinstance(preflight, dict):
        safe["preflight"] = {
            key: value for key, value in preflight.items() if key != "migration_plan"
        }
    safe["migrations"] = [
        {
            "id": migration["id"],
            "description": migration["description"],
            "status": migration["status"],
            "planned_statement_types": [_statement_type(sql) for sql in migration["sql"]],
            "will_execute": migration["will_execute"],
        }
        for migration in result.get("migrations", [])
    ]
    return safe


def _statement_type(sql: str) -> str:
    return sql.strip().split(maxsplit=2)[0].upper() if sql.strip() else "SQL"


if __name__ == "__main__":
    raise SystemExit(main())
