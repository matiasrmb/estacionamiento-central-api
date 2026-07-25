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


def solo_lavado_idempotency_key(id_operacion_servicio: int) -> str:
    return f"api-solo-lavado:{id_operacion_servicio}:pc-pdf"


def crear_print_job_solo_lavado(conn: Connection, operation: dict, fecha_hora_fin, usuario: str) -> bool:
    id_operacion = int(operation["id_operacion_servicio"])
    hora_inicio = operation["fecha_hora_inicio"].replace(microsecond=0).isoformat(sep=" ")
    hora_fin = fecha_hora_fin.replace(microsecond=0).isoformat(sep=" ")
    monto_final = int(operation["valor_lavado_snapshot"])
    servicio = str(operation.get("tipo_vehiculo_lavado_snapshot") or "Lavado")
    payload = {
        "kind": "TICKET_SOLO_LAVADO",
        "id_operacion_servicio": id_operacion,
        "patente": operation["patente"],
        "servicio": servicio,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "minutos": max(0, int((fecha_hora_fin - operation["fecha_hora_inicio"]).total_seconds() // 60)),
        "monto_final": monto_final,
        "total": monto_final,
        "detalle_texto": f"Lavado {servicio}",
        "usuario": {"usuario": usuario},
        "meta": {"server_time": hora_fin, "version": 1},
    }
    return crear_print_job(
        conn,
        tipo="TICKET_SOLO_LAVADO",
        destino="PC_PDF",
        id_ingreso=None,
        patente=operation["patente"],
        payload=payload,
        idempotency_key=solo_lavado_idempotency_key(id_operacion),
        prioridad=50,
    )
