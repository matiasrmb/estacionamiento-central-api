import json
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.core.logging import setup_logging
from app.core.slowlog import log_if_slow
from app.db.database import engine

from printer_agent.pdf_renderer import render_ticket_pdf
from printer_agent.pdf_printer import (
    AmbiguousPrintDispatchError,
    PrintDispatchStartError,
    print_pdf_with_sumatra,
)


setup_logging()
logger = logging.getLogger("print_agent")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


PRINT_ENGINE = _env_str("PRINT_ENGINE", "SUMATRA").upper()
SUMATRA_PATH = _env_str("SUMATRA_PATH", "")
PRINTER_NAME = _env_str("PRINTER_NAME", "POS58 Printer")
WORKDIR = _env_str("PRINT_WORKDIR", "print_out")
AGENT_ID = _env_str("AGENT_ID", "PC-PRINT-AGENT-01")

POLL_INTERVAL = _env_int("POLL_INTERVAL_SECONDS", 1)
PRINT_TIMEOUT = _env_int("PRINT_TIMEOUT_SECONDS", 20)

# Si un job queda IMPRIMIENDO por caída del agente, lo liberamos tras X segundos
STALE_LOCK_SECONDS = _env_int("STALE_LOCK_SECONDS", 60)


@contextmanager
def slow_print_step(operation: str, **context: Any):
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        log_if_slow(
            logger,
            threshold_env="SLOW_PRINT_JOB_MS",
            default_ms=3000,
            area="print_agent",
            operation=operation,
            duration_ms=duration_ms,
            context=context,
        )


def release_stale_locks() -> None:
    """
    Libera jobs atascados en IMPRIMIENDO por más de STALE_LOCK_SECONDS.
    Un despacho que pudo llegar al spooler queda bloqueado para evitar duplicados.
    """
    with slow_print_step("release_stale_locks"):
        with engine.begin() as conn:
            conn.execute(
                text("""
                UPDATE print_jobs
                SET estado=CASE
                        WHEN last_error LIKE :dispatch_started_prefix THEN 'REVISION_MANUAL'
                        ELSE 'ERROR'
                    END,
                    next_retry_at=CASE
                        WHEN last_error LIKE :dispatch_started_prefix THEN NULL
                        ELSE NOW()
                    END,
                    last_error=CASE
                        WHEN last_error LIKE :dispatch_started_prefix
                            THEN CONCAT('AMBIGUOUS_PRINT_DISPATCH: ', last_error)
                        ELSE COALESCE(last_error, 'Stale lock released')
                    END,
                    locked_at=NULL,
                    locked_by=NULL,
                    updated_at=NOW()
                WHERE destino='PC_PDF'
                  AND estado='IMPRIMIENDO'
                  AND locked_at IS NOT NULL
                  AND locked_at < DATE_SUB(NOW(), INTERVAL :sec SECOND)
                """),
                {
                    "sec": STALE_LOCK_SECONDS,
                    "dispatch_started_prefix": "AMBIGUOUS_PRINT_DISPATCH_STARTED:%",
                },
            )


def claim_next_job() -> Optional[Dict[str, Any]]:
    """
    Reclama 1 job elegible y lo marca IMPRIMIENDO.
    IMPORTANTE: esto se hace y se COMMITTEA antes de imprimir (evita loops).
    """
    with slow_print_step("claim_job"):
        with engine.begin() as conn:
            row = conn.execute(
                text("""
                SELECT id_print_job, tipo, destino, id_ingreso, patente, payload_json, intentos, max_intentos
                FROM print_jobs
                WHERE destino='PC_PDF'
                  AND (
                    estado='PENDIENTE'
                    OR (estado='ERROR' AND (next_retry_at IS NULL OR next_retry_at <= NOW()))
                  )
                  AND intentos < max_intentos
                ORDER BY prioridad ASC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """)
            ).mappings().first()

            if not row:
                return None

            conn.execute(
                text("""
                UPDATE print_jobs
                SET estado='IMPRIMIENDO',
                    locked_at=NOW(),
                    locked_by=:agent,
                    updated_at=NOW()
                WHERE id_print_job=:id
                """),
                {"agent": AGENT_ID, "id": row["id_print_job"]},
            )

            # engine.begin() hace commit automático al salir
            return dict(row)


def mark_printed(job_id: int) -> None:
    with slow_print_step("mark_printed", job_id=job_id):
        with engine.begin() as conn:
            conn.execute(
                text("""
                UPDATE print_jobs
                SET estado='IMPRESO',
                    last_error=NULL,
                    locked_at=NULL,
                    locked_by=NULL,
                    updated_at=NOW()
                WHERE id_print_job=:id
                """),
                {"id": job_id},
            )


def mark_dispatch_started(job_id: int) -> None:
    """Persists the ambiguity marker before handing the PDF to Sumatra."""
    with slow_print_step("mark_dispatch_started", job_id=job_id):
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                UPDATE print_jobs
                SET last_error=:err,
                    updated_at=NOW()
                WHERE id_print_job=:id
                  AND estado='IMPRIMIENDO'
                  AND locked_by=:agent
                """),
                {
                    "id": job_id,
                    "agent": AGENT_ID,
                    "err": f"AMBIGUOUS_PRINT_DISPATCH_STARTED: agent={AGENT_ID}"[:500],
                },
            )
            if result.rowcount != 1:
                raise RuntimeError(
                    f"Could not persist dispatch-start marker for job id={job_id}"
                )


def mark_error(job_id: int, err_msg: str) -> None:
    """
    Backoff lineal simple:
      next_retry_at = NOW() + (intentos+1)*10 segundos
    """
    with slow_print_step("mark_error", job_id=job_id):
        with engine.begin() as conn:
            # Leemos intentos actuales para calcular delay
            cur = conn.execute(
                text("""
                SELECT intentos
                FROM print_jobs
                WHERE id_print_job=:id
                  AND estado='IMPRIMIENDO'
                  AND locked_by=:agent
                LIMIT 1
                """),
                {"id": job_id, "agent": AGENT_ID},
            ).scalar()
            if cur is None:
                logger.warning("Skipped marking ERROR for job id=%s because it is not locked by this agent", job_id)
                return

            intentos = int(cur or 0)
            delay = (intentos + 1) * 10

            conn.execute(
                text("""
                UPDATE print_jobs
                SET estado='ERROR',
                    intentos=intentos+1,
                    next_retry_at=DATE_ADD(NOW(), INTERVAL :delay SECOND),
                    last_error=:err,
                    locked_at=NULL,
                    locked_by=NULL,
                    updated_at=NOW()
                WHERE id_print_job=:id
                  AND estado='IMPRIMIENDO'
                  AND locked_by=:agent
                """),
                {"id": job_id, "agent": AGENT_ID, "err": err_msg[:500], "delay": delay},
            )


def mark_ambiguous_dispatch_error(job_id: int, err_msg: str) -> None:
    """Blocks automatic retry when a ticket may already be in the spooler."""
    with slow_print_step("mark_ambiguous_dispatch_error", job_id=job_id):
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                UPDATE print_jobs
                SET estado='REVISION_MANUAL',
                    next_retry_at=NULL,
                    last_error=:err,
                    locked_at=NULL,
                    locked_by=NULL,
                    updated_at=NOW()
                WHERE id_print_job=:id
                  AND estado='IMPRIMIENDO'
                  AND locked_by=:agent
                """),
                {
                    "id": job_id,
                    "agent": AGENT_ID,
                    "err": f"AMBIGUOUS_PRINT_DISPATCH: {err_msg}"[:500],
                },
            )
            if result.rowcount != 1:
                logger.warning("Skipped blocking ambiguous dispatch for job id=%s because it is not locked by this agent", job_id)


def run_loop() -> None:
    if not PRINTER_NAME:
        raise RuntimeError("PRINTER_NAME no está configurado. Define PRINTER_NAME en tu .env o variables de entorno.")
    if PRINT_ENGINE == "SUMATRA" and not SUMATRA_PATH:
        raise RuntimeError("SUMATRA_PATH no está configurado. Define SUMATRA_PATH con la ruta a SumatraPDF.exe.")

    logger.info("Print Agent starting: agent_id=%s printer=%s", AGENT_ID, PRINTER_NAME)
    logger.info("Sumatra path: %s", SUMATRA_PATH)

    while True:
        job_id = None
        dispatch_may_have_started = False
        try:
            # 1) Liberar locks viejos (seguridad)
            release_stale_locks()

            # 2) Tomar un job (commit inmediato)
            job = claim_next_job()
            if not job:
                time.sleep(POLL_INTERVAL)
                continue

            job_id = int(job["id_print_job"])
            logger.info("Claimed job id=%s tipo=%s patente=%s", job_id, job["tipo"], job.get("patente"))

            # 3) Parse payload
            payload = job["payload_json"]
            if isinstance(payload, str):
                payload = json.loads(payload)

            # 4) Render PDF
            with slow_print_step("render_pdf", job_id=job_id):
                pdf_path = render_ticket_pdf(payload, WORKDIR)

            # 5) Print (Sumatra recomendado para estabilidad post-reinicio)
            if PRINT_ENGINE != "SUMATRA":
                raise RuntimeError("MVP requiere PRINT_ENGINE=SUMATRA. Acrobat es inestable post-reinicio.")

            # This commits before Sumatra starts, so a crash cannot make a possible
            # physical dispatch eligible for automatic retry.
            mark_dispatch_started(job_id)
            dispatch_may_have_started = True
            with slow_print_step("print_pdf", job_id=job_id, printer=PRINTER_NAME):
                print_pdf_with_sumatra(
                    sumatra_path=SUMATRA_PATH,
                    pdf_path=pdf_path,
                    printer_name=PRINTER_NAME,
                    timeout_seconds=PRINT_TIMEOUT,
                )
            # 6) Marcar impreso (transacción aparte)
            mark_printed(job_id)
            logger.info("Printed OK job id=%s pdf=%s", job_id, pdf_path)

        except Exception as exc:
            # Si ocurrió después de claim, intentamos marcar error sólo para el job de esta iteración.
            logger.exception("Agent error: %s", exc)
            try:
                if job_id is not None:
                    if (
                        isinstance(exc, AmbiguousPrintDispatchError)
                        or (
                            dispatch_may_have_started
                            and not isinstance(exc, PrintDispatchStartError)
                        )
                    ):
                        mark_ambiguous_dispatch_error(job_id, str(exc))
                    else:
                        mark_error(job_id, str(exc))
            except Exception:
                logger.exception("Failed to mark ERROR for job")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_loop()
