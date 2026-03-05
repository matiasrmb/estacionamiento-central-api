import json
from sqlalchemy import text
from sqlalchemy.engine import Connection


def crear_print_job(
    conn: Connection,
    *,
    tipo: str,
    destino: str,
    id_ingreso: int | None,
    patente: str | None,
    payload: dict,
    idempotency_key: str,
    prioridad: int = 100,
) -> bool:
    payload_json = json.dumps(payload, ensure_ascii=False)

    res = conn.execute(
        text("""
            INSERT IGNORE INTO print_jobs
            (tipo, destino, id_ingreso, patente, payload_json, estado, prioridad, idempotency_key, created_at, updated_at)
            VALUES
            (:tipo, :destino, :id_ingreso, :patente, CAST(:payload AS JSON), 'PENDIENTE', :prioridad, :idem, NOW(), NOW())
        """),
        {
            "tipo": tipo,
            "destino": destino,
            "id_ingreso": id_ingreso,
            "patente": patente,
            "payload": payload_json,
            "prioridad": prioridad,
            "idem": idempotency_key,
        },
    )
    return getattr(res, "rowcount", 0) == 1