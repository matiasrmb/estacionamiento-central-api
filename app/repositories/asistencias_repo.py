from datetime import date, datetime, time
from typing import Any, Dict

from sqlalchemy import text

from app.db.database import db_conn


def registrar_asistencia_inicio(usuario: str) -> None:
    now = datetime.now()
    with db_conn() as conn:
        _cerrar_asistencias_activas(conn, usuario, now)
        conn.execute(
            text("""
                INSERT INTO asistencias (usuario, hora_inicio)
                VALUES (:usuario, :hora_inicio)
            """),
            {"usuario": usuario, "hora_inicio": now},
        )
        conn.commit()


def registrar_asistencia_salida(usuario: str) -> Dict[str, Any]:
    now = datetime.now()
    with db_conn() as conn:
        resumen = _cerrar_asistencias_activas(conn, usuario, now)
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
        SELECT usuario, hora_inicio, hora_salida, cantidad_movimientos, total_recaudado
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


def _cerrar_asistencias_activas(conn, usuario: str, hora_salida: datetime) -> Dict[str, Any]:
    rows = conn.execute(
        text("""
            SELECT id_asistencia, hora_inicio
            FROM asistencias
            WHERE usuario = :usuario
              AND hora_salida IS NULL
            ORDER BY hora_inicio ASC
        """),
        {"usuario": usuario},
    ).mappings().all()

    resumen = {"cantidad": 0, "total": 0, "hora_inicio": None}
    for row in rows:
        totals = _calcular_totales_turno(conn, usuario, row["hora_inicio"], hora_salida)
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
        totals = _calcular_totales_turno(conn, row["usuario"], row["hora_inicio"], now)
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


def _calcular_totales_turno(conn, usuario: str, inicio: datetime, fin: datetime) -> Dict[str, int]:
    salidas = conn.execute(
        text("""
            SELECT COUNT(*) AS cantidad, COALESCE(SUM(tarifa_aplicada), 0) AS total
            FROM ingresos
            WHERE usuario = :usuario
              AND fecha_hora_salida BETWEEN :inicio AND :fin
        """),
        {"usuario": usuario, "inicio": inicio, "fin": fin},
    ).mappings().first()
    banos = conn.execute(
        text("""
            SELECT COUNT(*) AS cantidad, COALESCE(SUM(monto), 0) AS total
            FROM usos_bano
            WHERE usuario = :usuario
              AND fecha_hora BETWEEN :inicio AND :fin
        """),
        {"usuario": usuario, "inicio": inicio, "fin": fin},
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
