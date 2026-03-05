import json
import logging
import os
import time
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.core.logging import setup_logging
from app.db.database import engine

from printer_agent.pdf_renderer import render_ticket_pdf
from printer_agent.pdf_printer import print_pdf_with_sumatra


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
SUMATRA_PATH = _env_str("SUMATRA_PATH", r"C:\Users\matia\AppData\Local\SumatraPDF\SumatraPDF.exe")
PRINTER_NAME = _env_str("PRINTER_NAME", "POS58 Printer")
WORKDIR = _env_str("PRINT_WORKDIR", "print_out")
AGENT_ID = _env_str("AGENT_ID", "PC-PRINT-AGENT-01")

POLL_INTERVAL = _env_int("POLL_INTERVAL_SECONDS", 1)
PRINT_SLEEP = _env_int("PRINT_SLEEP_SECONDS", 2)
PRINT_TIMEOUT = _env_int("PRINT_TIMEOUT_SECONDS", 20)

# Si un job queda IMPRIMIENDO por caída del agente, lo liberamos tras X segundos
STALE_LOCK_SECONDS = _env_int("STALE_LOCK_SECONDS", 60)


def release_stale_locks() -> None:
    """
    Libera jobs atascados en IMPRIMIENDO por más de STALE_LOCK_SECONDS.
    Los pasa a ERROR para reintento.
    """
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE print_jobs
                SET estado='ERROR',
                    next_retry_at=NOW(),
                    last_error=COALESCE(last_error, 'Stale lock released'),
                    locked_at=NULL,
                    locked_by=NULL,
                    updated_at=NOW()
                WHERE destino='PC_PDF'
                  AND estado='IMPRIMIENDO'
                  AND locked_at IS NOT NULL
                  AND locked_at < DATE_SUB(NOW(), INTERVAL :sec SECOND)
            """),
            {"sec": STALE_LOCK_SECONDS},
        )


def claim_next_job() -> Optional[Dict[str, Any]]:
    """
    Reclama 1 job elegible y lo marca IMPRIMIENDO.
    IMPORTANTE: esto se hace y se COMMITTEA antes de imprimir (evita loops).
    """
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


def mark_error(job_id: int, err_msg: str) -> None:
    """
    Backoff lineal simple:
      next_retry_at = NOW() + (intentos+1)*10 segundos
    """
    with engine.begin() as conn:
        # Leemos intentos actuales para calcular delay
        cur = conn.execute(
            text("SELECT intentos FROM print_jobs WHERE id_print_job=:id LIMIT 1"),
            {"id": job_id},
        ).scalar()
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
            """),
            {"id": job_id, "err": err_msg[:500], "delay": delay},
        )


def run_loop() -> None:
    if not PRINTER_NAME:
        raise RuntimeError("PRINTER_NAME no está configurado. Define PRINTER_NAME en tu .env o variables de entorno.")

    logger.info("Print Agent starting: agent_id=%s printer=%s", AGENT_ID, PRINTER_NAME)
    logger.info("Sumatra path: %s", SUMATRA_PATH)

    while True:
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
            pdf_path = render_ticket_pdf(payload, WORKDIR)

            # 5) Print (Sumatra recomendado para estabilidad post-reinicio)
            if PRINT_ENGINE != "SUMATRA":
                raise RuntimeError("MVP requiere PRINT_ENGINE=SUMATRA. Acrobat es inestable post-reinicio.")

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
            # Si ocurrió después de claim, intentamos marcar error usando job_id si existe
            logger.exception("Agent error: %s", exc)
            try:
                if "job_id" in locals():
                    mark_error(int(job_id), str(exc))
            except Exception:
                logger.exception("Failed to mark ERROR for job")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_loop()