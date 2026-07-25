from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.db.database import db_conn
from app.db.schema_ensure import ensure_operaciones_servicio_schema, ensure_wash_vehicle_type_schema
from app.services.print_jobs import crear_print_job_solo_lavado

from app.schemas.operaciones_servicio import OperacionServicioContrato, OperacionServicioState


ESTADO_ACTIVO = OperacionServicioState.ACTIVO.value
ESTADO_FINALIZADO_COBRADO = OperacionServicioState.FINALIZADO_COBRADO.value
ESTADO_CONVERTIDO_ESTADIA = OperacionServicioState.CONVERTIDO_ESTADIA.value

_ESTADOS_FINALES = {ESTADO_FINALIZADO_COBRADO, ESTADO_CONVERTIDO_ESTADIA}


def build_operacion_servicio_inicio(
    patente: str,
    wash_snapshot: Dict[str, Any],
    usuario_inicio: str,
    fecha_hora_inicio: str,
) -> OperacionServicioContrato:
    return OperacionServicioContrato(
        patente=str(patente).upper(),
        id_tipo_vehiculo_lavado=int(wash_snapshot["id_tipo_vehiculo_lavado"]),
        tipo_vehiculo_lavado_snapshot=str(wash_snapshot["tipo_vehiculo_lavado_snapshot"]),
        valor_lavado_snapshot=int(wash_snapshot["valor_lavado_snapshot"]),
        fecha_hora_inicio=fecha_hora_inicio,
        usuario_inicio=usuario_inicio,
        estado=OperacionServicioState.ACTIVO,
    )


def transition_operacion_servicio(
    operacion: Any,
    nuevo_estado: str,
    usuario_fin: str,
    fecha_hora_fin: str,
    id_ingreso_generado: Optional[int] = None,
) -> OperacionServicioContrato:
    payload = _as_dict(operacion)
    if _state_value(payload.get("estado")) != ESTADO_ACTIVO:
        raise ValueError("OPERACION_SERVICIO_NOT_ACTIVE")

    if nuevo_estado not in _ESTADOS_FINALES:
        raise ValueError("OPERACION_SERVICIO_INVALID_TRANSITION")

    if nuevo_estado == ESTADO_CONVERTIDO_ESTADIA and id_ingreso_generado is None:
        raise ValueError("OPERACION_SERVICIO_REQUIRES_INGRESO_GENERADO")

    payload.update({
        "estado": nuevo_estado,
        "fecha_hora_fin": fecha_hora_fin,
        "usuario_fin": usuario_fin,
        "id_ingreso_generado": id_ingreso_generado,
        "cobra_ahora": nuevo_estado == ESTADO_FINALIZADO_COBRADO,
    })
    return OperacionServicioContrato(**payload)


def _as_dict(operacion: Any) -> Dict[str, Any]:
    if isinstance(operacion, OperacionServicioContrato):
        return operacion.model_dump()
    return dict(operacion)


def _state_value(estado: Any) -> str:
    return getattr(estado, "value", estado)


def iniciar_solo_lavado(patente: str, id_tipo_vehiculo_lavado: int, usuario: str) -> Dict[str, Any]:
    ensure_wash_vehicle_type_schema()
    ensure_operaciones_servicio_schema()
    patente = patente.strip().upper()
    now = datetime.now()
    with db_conn() as conn:
        active_ingreso = conn.execute(text("""
            SELECT i.id_ingreso
            FROM ingresos i
            JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
            WHERE v.patente = :patente
              AND i.fecha_hora_salida IS NULL
              AND i.en_espera = 0
            LIMIT 1
        """), {"patente": patente}).first()
        if active_ingreso:
            raise RuntimeError("ACTIVE_INGRESO_EXISTS")

        active_operation = conn.execute(text("""
            SELECT id_operacion_servicio
            FROM operaciones_servicio
            WHERE patente = :patente
              AND estado = 'ACTIVO'
            LIMIT 1
        """), {"patente": patente}).first()
        if active_operation:
            raise RuntimeError("SOLO_WASH_ALREADY_ACTIVE")

        wash_type = conn.execute(text("""
            SELECT id_tipo_vehiculo_lavado, nombre, valor_lavado, activo
            FROM tipos_vehiculo_lavado
            WHERE id_tipo_vehiculo_lavado = :id
            LIMIT 1
        """), {"id": id_tipo_vehiculo_lavado}).mappings().first()
        if not wash_type:
            raise LookupError("WASH_VEHICLE_TYPE_NOT_FOUND")
        if not int(wash_type.get("activo") or 0):
            raise ValueError("INACTIVE_WASH_VEHICLE_TYPE")

        conn.execute(text("""
            INSERT INTO operaciones_servicio (
                patente, id_tipo_vehiculo_lavado, tipo_vehiculo_lavado_snapshot,
                valor_lavado_snapshot, fecha_hora_inicio, usuario_inicio, estado
            ) VALUES (
                :patente, :id_tipo_vehiculo_lavado, :tipo_vehiculo_lavado_snapshot,
                :valor_lavado_snapshot, :fecha_hora_inicio, :usuario_inicio, 'ACTIVO'
            )
        """), {
            "patente": patente,
            "id_tipo_vehiculo_lavado": int(wash_type["id_tipo_vehiculo_lavado"]),
            "tipo_vehiculo_lavado_snapshot": str(wash_type["nombre"]),
            "valor_lavado_snapshot": int(wash_type["valor_lavado"]),
            "fecha_hora_inicio": now,
            "usuario_inicio": usuario,
        })
        new_id = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())
        conn.commit()

    return {
        "id_operacion_servicio": new_id,
        "patente": patente,
        "estado": ESTADO_ACTIVO,
        "valor_lavado_snapshot": int(wash_type["valor_lavado"]),
        "fecha_hora_inicio": now.isoformat(),
    }


def list_solo_lavados_activos(patente: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_operaciones_servicio_schema()
    filters = ["estado = 'ACTIVO'"]
    params: Dict[str, Any] = {}
    if patente:
        filters.append("patente = :patente")
        params["patente"] = patente.strip().upper()

    with db_conn() as conn:
        rows = conn.execute(text(f"""
            SELECT id_operacion_servicio, patente, estado,
                   id_tipo_vehiculo_lavado, tipo_vehiculo_lavado_snapshot,
                   valor_lavado_snapshot, fecha_hora_inicio,
                   TIMESTAMPDIFF(MINUTE, fecha_hora_inicio, NOW()) AS duracion_minutos
            FROM operaciones_servicio
            WHERE {' AND '.join(filters)}
            ORDER BY fecha_hora_inicio DESC
        """), params).mappings().all()

    return [
        {
            "id_operacion_servicio": int(row["id_operacion_servicio"]),
            "patente": row["patente"],
            "estado": row["estado"],
            "id_tipo_vehiculo_lavado": int(row["id_tipo_vehiculo_lavado"]),
            "tipo_vehiculo_lavado_snapshot": row["tipo_vehiculo_lavado_snapshot"],
            "valor_lavado_snapshot": int(row["valor_lavado_snapshot"]),
            "fecha_hora_inicio": row["fecha_hora_inicio"].isoformat(),
            "duracion_minutos": int(row["duracion_minutos"] or 0),
        }
        for row in rows
    ]


def finalizar_solo_lavado_cobrar(id_operacion_servicio: int, usuario: str) -> Dict[str, Any]:
    ensure_operaciones_servicio_schema()
    now = datetime.now()
    with db_conn() as conn:
        operation = _get_active_operation(conn, id_operacion_servicio)
        conn.execute(text("""
            UPDATE operaciones_servicio
            SET estado = 'FINALIZADO_COBRADO', fecha_hora_fin = :fecha_hora_fin,
                duracion_minutos = TIMESTAMPDIFF(MINUTE, fecha_hora_inicio, :fecha_hora_fin),
                usuario_fin = :usuario_fin
            WHERE id_operacion_servicio = :id
        """), {"fecha_hora_fin": now, "usuario_fin": usuario, "id": id_operacion_servicio})
        try:
            if not crear_print_job_solo_lavado(conn, operation, now, usuario):
                raise RuntimeError("SOLO_WASH_PRINT_JOB_NOT_CREATED")
        except Exception:
            conn.rollback()
            raise
        conn.commit()

    return _finalized_payload(operation, ESTADO_FINALIZADO_COBRADO, now, usuario, True)


def convertir_solo_lavado_a_estadia(id_operacion_servicio: int, usuario: str) -> Dict[str, Any]:
    ensure_operaciones_servicio_schema()
    now = datetime.now()
    with db_conn() as conn:
        operation = _get_active_operation(conn, id_operacion_servicio)
        id_vehiculo = _get_or_create_vehicle(conn, operation["patente"])
        conn.execute(text("""
            INSERT INTO ingresos (id_vehiculo, fecha_hora_ingreso, usuario)
            VALUES (:id_vehiculo, :fecha_hora_ingreso, :usuario)
        """), {"id_vehiculo": id_vehiculo, "fecha_hora_ingreso": now, "usuario": usuario})
        id_ingreso = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())
        conn.execute(text("""
            UPDATE operaciones_servicio
            SET estado = 'CONVERTIDO_ESTADIA', fecha_hora_fin = :fecha_hora_fin,
                duracion_minutos = TIMESTAMPDIFF(MINUTE, fecha_hora_inicio, :fecha_hora_fin),
                usuario_fin = :usuario_fin, id_ingreso_generado = :id_ingreso
            WHERE id_operacion_servicio = :id
        """), {
            "fecha_hora_fin": now,
            "usuario_fin": usuario,
            "id_ingreso": id_ingreso,
            "id": id_operacion_servicio,
        })
        conn.commit()

    payload = _finalized_payload(operation, ESTADO_CONVERTIDO_ESTADIA, now, usuario, False)
    payload["id_ingreso_generado"] = id_ingreso
    payload["fecha_hora_ingreso"] = now.isoformat()
    return payload


def _get_active_operation(conn, id_operacion_servicio: int):
    operation = conn.execute(text("""
        SELECT id_operacion_servicio, patente, estado, valor_lavado_snapshot,
               tipo_vehiculo_lavado_snapshot, fecha_hora_inicio
        FROM operaciones_servicio
        WHERE id_operacion_servicio = :id
        LIMIT 1
    """), {"id": id_operacion_servicio}).mappings().first()
    if not operation:
        raise LookupError("SOLO_WASH_NOT_FOUND")
    if operation["estado"] != ESTADO_ACTIVO:
        raise RuntimeError("SOLO_WASH_NOT_ACTIVE")
    return operation


def _get_or_create_vehicle(conn, patente: str) -> int:
    row = conn.execute(
        text("SELECT id_vehiculo FROM vehiculos WHERE patente = :patente LIMIT 1"),
        {"patente": patente},
    ).first()
    if row:
        return int(row[0])
    conn.execute(text("INSERT INTO vehiculos (patente) VALUES (:patente)"), {"patente": patente})
    return int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())


def _finalized_payload(operation, estado: str, fecha_hora_fin, usuario: str, cobra_ahora: bool) -> Dict[str, Any]:
    return {
        "id_operacion_servicio": int(operation["id_operacion_servicio"]),
        "patente": operation["patente"],
        "estado": estado,
        "cobra_ahora": cobra_ahora,
        "valor_lavado_snapshot": int(operation["valor_lavado_snapshot"]),
        "fecha_hora_fin": fecha_hora_fin.isoformat(),
        "usuario_fin": usuario,
    }
