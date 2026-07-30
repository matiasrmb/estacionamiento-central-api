from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn
from app.db.schema_ensure import ensure_gastos_operacion_schema


def crear_gasto(categoria: str, descripcion: str, monto: int, usuario: str) -> Dict[str, Any]:
    ensure_gastos_operacion_schema()
    fecha_hora = datetime.now()
    with db_conn() as conn:
        conn.execute(
            text("""
                INSERT INTO gastos_operacion (fecha_hora, categoria, descripcion, monto, usuario)
                VALUES (:fecha_hora, :categoria, :descripcion, :monto, :usuario)
            """),
            {
                "fecha_hora": fecha_hora,
                "categoria": categoria,
                "descripcion": descripcion,
                "monto": monto,
                "usuario": usuario,
            },
        )
        id_gasto = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())
        conn.commit()

    return {
        "id_gasto": id_gasto,
        "fecha_hora": fecha_hora.isoformat(),
        "categoria": categoria,
        "descripcion": descripcion,
        "monto": int(monto),
        "usuario": usuario,
        "id_cierre": None,
    }


def list_gastos_pendientes() -> Dict[str, Any]:
    ensure_gastos_operacion_schema()
    with db_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT id_gasto, fecha_hora, categoria, descripcion, monto, usuario, id_cierre
                FROM gastos_operacion
                WHERE id_cierre IS NULL
                ORDER BY fecha_hora ASC, id_gasto ASC
            """)
        ).mappings().all()

    items = [_serialize_gasto(row) for row in rows]
    return {"items": items, "total_gastos": sum(item["monto"] for item in items)}


def _serialize_gasto(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    fecha_hora = item.get("fecha_hora")
    item["fecha_hora"] = fecha_hora.isoformat() if hasattr(fecha_hora, "isoformat") else str(fecha_hora)
    item["id_gasto"] = int(item["id_gasto"])
    item["monto"] = int(item["monto"] or 0)
    item["id_cierre"] = int(item["id_cierre"]) if item.get("id_cierre") is not None else None
    return item
