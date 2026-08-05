from datetime import date, datetime, time
from typing import Any, Dict

from sqlalchemy import text

from app.db.database import db_conn


def registrar_asistencia_inicio(usuario: str, device_id: str, session_id: str) -> None:
    now = datetime.now()
    with db_conn() as conn:
        conn.execute(
            text("""
                INSERT INTO asistencias (usuario, device_id, session_id, hora_inicio)
                VALUES (:usuario, :device_id, :session_id, :hora_inicio)
            """),
            {"usuario": usuario, "device_id": device_id, "session_id": session_id, "hora_inicio": now},
        )
        conn.commit()


def registrar_asistencia_salida(usuario: str, session_id: str) -> Dict[str, Any]:
    now = datetime.now()
    if not session_id.strip():
        return {"cantidad": 0, "total": 0, "hora_inicio": None}
    with db_conn() as conn:
        resumen = _cerrar_asistencias_activas(conn, usuario, now, session_id=session_id)
        conn.commit()
    return resumen


def cerrar_asistencias_activas(usuario: str = "") -> Dict[str, int]:
    now = datetime.now()
    usuario = usuario.strip()
    with db_conn() as conn:
        if usuario:
            usuarios = [usuario]
        else:
            rows = conn.execute(
                text("""
                    SELECT DISTINCT usuario
                    FROM asistencias
                    WHERE hora_salida IS NULL
                """)
            ).fetchall()
            usuarios = [row[0] for row in rows]

        cerradas = 0
        for user in usuarios:
            before = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM asistencias
                    WHERE usuario = :usuario AND hora_salida IS NULL
                """),
                {"usuario": user},
            ).scalar()
            _cerrar_asistencias_activas(conn, user, now)
            cerradas += int(before or 0)
        conn.commit()
    return {"cerradas": cerradas}


def obtener_asistencias(usuario: str = "", fecha_inicio: date | None = None, fecha_fin: date | None = None) -> Dict[str, Any]:
    query = """
        SELECT id_asistencia, usuario, hora_inicio, hora_salida, cantidad_movimientos, total_recaudado
        FROM asistencias
        WHERE 1=1
    """
    params: Dict[str, Any] = {}

    usuario = usuario.strip()
    if usuario:
        query += " AND usuario = :usuario"
        params["usuario"] = usuario

    if fecha_inicio and fecha_fin:
        inicio = datetime.combine(fecha_inicio, time.min)
        fin = datetime.combine(fecha_fin, time.max)
        query += " AND hora_inicio BETWEEN :inicio AND :fin"
        params["inicio"] = inicio
        params["fin"] = fin

    query += " ORDER BY hora_inicio DESC"

    now = datetime.now()
    with db_conn() as conn:
        rows = conn.execute(text(query), params).mappings().all()
        items = [_serialize(conn, row, now) for row in rows]

    total_recaudado = sum(int(item["total_recaudado"] or 0) for item in items)
    return {
        "usuario": usuario,
        "fecha_inicio": fecha_inicio.isoformat() if fecha_inicio else None,
        "fecha_fin": fecha_fin.isoformat() if fecha_fin else None,
        "items": items,
        "total_registros": len(items),
        "total_recaudado": total_recaudado,
    }


def _cerrar_asistencias_activas(
    conn, usuario: str, hora_salida: datetime, session_id: str | None = None
) -> Dict[str, Any]:
    session_filter = ""
    params = {"usuario": usuario}
    if session_id:
        session_filter = " AND session_id = :session_id"
        params["session_id"] = session_id
    rows = conn.execute(
        text("""
            SELECT id_asistencia, hora_inicio, session_id
            FROM asistencias
            WHERE usuario = :usuario
              AND hora_salida IS NULL
        """ + session_filter + """
            ORDER BY hora_inicio ASC
        """),
        params,
    ).mappings().all()

    resumen = {"cantidad": 0, "total": 0, "hora_inicio": None}
    for row in rows:
        totals = _calcular_totales_turno(
            conn,
            usuario,
            row["id_asistencia"],
            row["hora_inicio"],
            hora_salida,
            row.get("session_id"),
        )
        conn.execute(
            text("""
                UPDATE asistencias
                SET hora_salida = :hora_salida,
                    total_recaudado = :total,
                    cantidad_movimientos = :cantidad
                WHERE id_asistencia = :id_asistencia
            """),
            {
                "hora_salida": hora_salida,
                "total": totals["total"],
                "cantidad": totals["cantidad"],
                "id_asistencia": row["id_asistencia"],
            },
        )
        resumen = {"cantidad": totals["cantidad"], "total": totals["total"], "hora_inicio": row["hora_inicio"]}
    return resumen


def _serialize(conn, row, now: datetime) -> Dict[str, Any]:
    activa = row["hora_salida"] is None
    if activa:
        totals = _calcular_totales_turno(
            conn,
            row["usuario"],
            row["id_asistencia"],
            row["hora_inicio"],
            now,
            row.get("session_id"),
        )
        cantidad = totals["cantidad"]
        total = totals["total"]
    else:
        cantidad = int(row["cantidad_movimientos"] or 0)
        total = int(row["total_recaudado"] or 0)

    return {
        "usuario": row["usuario"],
        "hora_inicio": _iso(row["hora_inicio"]),
        "hora_salida": _iso(row["hora_salida"]),
        "cantidad_movimientos": cantidad,
        "total_recaudado": total,
        "activa": activa,
    }


def _calcular_totales_turno(
    conn,
    usuario: str,
    id_asistencia: int,
    inicio: datetime,
    fin: datetime,
    session_id: str | None = None,
) -> Dict[str, int]:
    # Sessionized attendance takes precedence over legacy rows; within each group,
    # the oldest attendance active at the movement timestamp owns the movement.
    params = {
        "usuario": usuario,
        "id_asistencia": id_asistencia,
        "inicio": inicio,
        "fin": fin,
        "session_id": session_id,
    }
    salidas = conn.execute(
        text("""
            SELECT COUNT(*) AS cantidad, COALESCE(SUM(tarifa_aplicada), 0) AS total
            FROM ingresos i
            WHERE i.usuario = :usuario
              AND i.fecha_hora_salida >= :inicio
              AND i.fecha_hora_salida < :fin
              AND (
                  :session_id IS NOT NULL
                  OR NOT EXISTS (
                      SELECT 1
                      FROM asistencias sessionizada
                      WHERE sessionizada.usuario = :usuario
                        AND sessionizada.session_id IS NOT NULL
                        AND sessionizada.hora_inicio <= i.fecha_hora_salida
                        AND (
                            sessionizada.hora_salida IS NULL
                            OR sessionizada.hora_salida > i.fecha_hora_salida
                        )
                  )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM asistencias anterior
                  WHERE anterior.usuario = :usuario
                    AND anterior.id_asistencia < :id_asistencia
                    AND anterior.hora_inicio <= i.fecha_hora_salida
                    AND (
                        anterior.hora_salida IS NULL
                        OR anterior.hora_salida > i.fecha_hora_salida
                    )
                    AND (
                        anterior.session_id IS NOT NULL
                        OR NOT EXISTS (
                            SELECT 1
                            FROM asistencias sessionizada
                            WHERE sessionizada.usuario = :usuario
                              AND sessionizada.session_id IS NOT NULL
                              AND sessionizada.hora_inicio <= i.fecha_hora_salida
                              AND (
                                  sessionizada.hora_salida IS NULL
                                  OR sessionizada.hora_salida > i.fecha_hora_salida
                              )
                        )
                    )
              )
        """),
        params,
    ).mappings().first()
    banos = conn.execute(
        text("""
            SELECT COUNT(*) AS cantidad, COALESCE(SUM(monto), 0) AS total
            FROM usos_bano b
            WHERE b.usuario = :usuario
              AND b.fecha_hora >= :inicio
              AND b.fecha_hora < :fin
              AND (
                  :session_id IS NOT NULL
                  OR NOT EXISTS (
                      SELECT 1
                      FROM asistencias sessionizada
                      WHERE sessionizada.usuario = :usuario
                        AND sessionizada.session_id IS NOT NULL
                        AND sessionizada.hora_inicio <= b.fecha_hora
                        AND (
                            sessionizada.hora_salida IS NULL
                            OR sessionizada.hora_salida > b.fecha_hora
                        )
                  )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM asistencias anterior
                  WHERE anterior.usuario = :usuario
                    AND anterior.id_asistencia < :id_asistencia
                    AND anterior.hora_inicio <= b.fecha_hora
                    AND (
                        anterior.hora_salida IS NULL
                        OR anterior.hora_salida > b.fecha_hora
                    )
                    AND (
                        anterior.session_id IS NOT NULL
                        OR NOT EXISTS (
                            SELECT 1
                            FROM asistencias sessionizada
                            WHERE sessionizada.usuario = :usuario
                              AND sessionizada.session_id IS NOT NULL
                              AND sessionizada.hora_inicio <= b.fecha_hora
                              AND (
                                  sessionizada.hora_salida IS NULL
                                  OR sessionizada.hora_salida > b.fecha_hora
                              )
                        )
                    )
              )
        """),
        params,
    ).mappings().first()

    return {
        "cantidad": int((salidas or {}).get("cantidad") or 0) + int((banos or {}).get("cantidad") or 0),
        "total": int((salidas or {}).get("total") or 0) + int((banos or {}).get("total") or 0),
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
