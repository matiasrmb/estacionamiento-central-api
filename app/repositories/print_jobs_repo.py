import json
from sqlalchemy import text
from sqlalchemy.engine import Connection
from app.db.database import db_conn


def create_print_job_pc_pdf_with_connection(
    conn: Connection, tipo: str, id_ingreso: int, patente: str, payload: dict, idempotency_key: str
) -> int:
    """
    Crea el job PC obligatorio usando una transacción administrada por el llamador.
    """
    query = """
      INSERT INTO print_jobs (tipo, destino, id_ingreso, patente, payload_json, estado, idempotency_key)
      VALUES (:tipo, 'PC_PDF', :id_ingreso, :patente, CAST(:payload AS JSON), 'PENDIENTE', :ikey)
    """
    conn.execute(
        text(query),
        {
            "tipo": tipo,
            "id_ingreso": id_ingreso,
            "patente": patente,
            "payload": json.dumps(payload, ensure_ascii=False),
            "ikey": idempotency_key,
        },
    )
    new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return int(new_id)


def create_print_job_pc_pdf(tipo: str, id_ingreso: int, patente: str, payload: dict, idempotency_key: str) -> int:
    """
    Crea job para impresión PC (PDF+Acrobat) en una transacción propia.

    Los flujos que necesitan atomicidad con otra escritura deben usar
    create_print_job_pc_pdf_with_connection.
    """
    with db_conn() as conn:
        new_id = create_print_job_pc_pdf_with_connection(
            conn,
            tipo=tipo,
            id_ingreso=id_ingreso,
            patente=patente,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        conn.commit()
        return new_id
