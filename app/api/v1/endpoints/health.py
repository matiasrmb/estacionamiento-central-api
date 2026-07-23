from fastapi import APIRouter, HTTPException
from sqlalchemy import bindparam, text

from app.db.database import db_conn

router = APIRouter()

REQUIRED_TABLES = {"usuarios", "vehiculos", "ingresos", "configuracion", "print_jobs"}
REQUIRED_PRINT_JOB_COLUMNS = {
    "id_print_job",
    "estado",
    "idempotency_key",
    "payload_json",
    "locked_by",
    "locked_at",
    "next_retry_at",
    "intentos",
    "max_intentos",
}


@router.get("/health", tags=["system"])
def health():
    """
    Healthcheck simple para verificar que la API está viva.
    """
    return {"status": "ok"}


def _fail(checks):
    return {"status": "fail", "checks": checks}


@router.get("/health/deep", tags=["system"])
def deep_health():
    """
    Healthcheck profundo para validar conectividad real a DB y esquema critico.
    """
    checks = {}
    try:
        with db_conn() as conn:
            conn.execute(text("SELECT 1"))
            checks["db_connection"] = {"status": "ok"}

            table_rows = conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name IN :tables
                    """
                ).bindparams(bindparam("tables", expanding=True)),
                {"tables": tuple(REQUIRED_TABLES)},
            )
            found_tables = {row[0] for row in table_rows}
            missing_tables = sorted(REQUIRED_TABLES - found_tables)
            checks["required_tables"] = {
                "status": "ok" if not missing_tables else "fail",
                "missing": missing_tables,
            }

            column_rows = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = 'print_jobs'
                      AND column_name IN :columns
                    """
                ).bindparams(bindparam("columns", expanding=True)),
                {"columns": tuple(REQUIRED_PRINT_JOB_COLUMNS)},
            )
            found_columns = {row[0] for row in column_rows}
            missing_columns = sorted(REQUIRED_PRINT_JOB_COLUMNS - found_columns)
            checks["print_jobs_columns"] = {
                "status": "ok" if not missing_columns else "fail",
                "missing": missing_columns,
            }
    except Exception:
        if "db_connection" in checks:
            checks["schema_query"] = {"status": "fail", "error": "schema check failed"}
        else:
            checks["db_connection"] = {"status": "fail", "error": "database check failed"}
        raise HTTPException(status_code=503, detail=_fail(checks))

    if any(check["status"] != "ok" for check in checks.values()):
        raise HTTPException(status_code=503, detail=_fail(checks))

    return {"status": "ok", "checks": checks}
