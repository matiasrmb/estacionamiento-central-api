from datetime import date, datetime, time
from typing import Any, Dict

from sqlalchemy import text

from app.db.database import db_conn


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

    with db_conn() as conn:
        rows = conn.execute(text(query), params).mappings().all()

    items = [_serialize(row) for row in rows]
    total_recaudado = sum(int(item["total_recaudado"] or 0) for item in items)
    return {
        "usuario": usuario,
        "fecha_inicio": fecha_inicio.isoformat() if fecha_inicio else None,
        "fecha_fin": fecha_fin.isoformat() if fecha_fin else None,
        "items": items,
        "total_registros": len(items),
        "total_recaudado": total_recaudado,
    }


def _serialize(row) -> Dict[str, Any]:
    return {
        "usuario": row["usuario"],
        "hora_inicio": _iso(row["hora_inicio"]),
        "hora_salida": _iso(row["hora_salida"]),
        "cantidad_movimientos": int(row["cantidad_movimientos"] or 0),
        "total_recaudado": int(row["total_recaudado"] or 0),
        "activa": row["hora_salida"] is None,
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
