import json
from sqlalchemy import text
from app.db.database import db_conn


def create_print_job_pc_pdf(tipo: str, id_ingreso: int, patente: str, payload: dict, idempotency_key: str) -> int:
    """
    Crea job para impresión PC (PDF+Acrobat) en tabla print_jobs.
    """
    query = """
      INSERT IGNORE INTO print_jobs (tipo, destino, id_ingreso, patente, payload_json, estado, idempotency_key)
      VALUES (:tipo, 'PC_PDF', :id_ingreso, :patente, CAST(:payload AS JSON), 'PENDIENTE', :ikey)
    """
    with db_conn() as conn:
        result = conn.execute(
            text(query),
            {
                "tipo": tipo,
                "id_ingreso": id_ingreso,
                "patente": patente,
                "payload": json.dumps(payload, ensure_ascii=False),
                "ikey": idempotency_key,
            },
        )
        conn.commit()
        if getattr(result, "rowcount", 0) == 1:
            new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        else:
            new_id = conn.execute(
                text("SELECT id_print_job FROM print_jobs WHERE idempotency_key = :ikey LIMIT 1"),
                {"ikey": idempotency_key},
            ).scalar()
        return int(new_id)
