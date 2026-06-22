from datetime import date
from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn


def obtener_reporte(fecha_inicio: date, fecha_fin: date, patente: str = "") -> Dict[str, Any]:
    patente = patente.strip().upper()
    query = """
        SELECT
            v.patente,
            i.fecha_hora_ingreso,
            i.fecha_hora_salida,
            TIMESTAMPDIFF(MINUTE, i.fecha_hora_ingreso, i.fecha_hora_salida) AS minutos,
            i.tarifa_aplicada
        FROM ingresos i
        JOIN vehiculos v ON i.id_vehiculo = v.id_vehiculo
        WHERE i.fecha_hora_salida IS NOT NULL
          AND DATE(i.fecha_hora_salida) BETWEEN :fecha_inicio AND :fecha_fin
    """
    params: Dict[str, Any] = {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin}

    if patente:
        query += " AND v.patente = :patente"
        params["patente"] = patente

    query += " ORDER BY i.fecha_hora_salida ASC"

    with db_conn() as conn:
        rows = conn.execute(text(query), params).mappings().all()
        items = [_serialize_movimiento(row) for row in rows]

        if not patente:
            banos = conn.execute(
                text("""
                    SELECT fecha_hora, monto, usuario
                    FROM usos_bano
                    WHERE DATE(fecha_hora) BETWEEN :fecha_inicio AND :fecha_fin
                    ORDER BY fecha_hora ASC
                """),
                params,
            ).mappings().all()
            for bano in banos:
                items.append(
                    {
                        "tipo": "bano",
                        "patente": "[BAÑO]",
                        "fecha_hora_ingreso": _iso(bano["fecha_hora"]),
                        "fecha_hora_salida": _iso(bano["fecha_hora"]),
                        "minutos": 0,
                        "tarifa_aplicada": int(bano["monto"] or 0),
                        "usuario": bano.get("usuario"),
                    }
                )

    items.sort(key=lambda item: item["fecha_hora_salida"] or "")
    total = sum(int(item["tarifa_aplicada"] or 0) for item in items)
    return {
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
        "patente": patente,
        "items": items,
        "total_movimientos": len(items),
        "total_recaudado": total,
    }


def _serialize_movimiento(row) -> Dict[str, Any]:
    return {
        "tipo": "vehiculo",
        "patente": row["patente"],
        "fecha_hora_ingreso": _iso(row["fecha_hora_ingreso"]),
        "fecha_hora_salida": _iso(row["fecha_hora_salida"]),
        "minutos": int(row["minutos"] or 0),
        "tarifa_aplicada": int(row["tarifa_aplicada"] or 0),
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
