import json
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn


class GastoNotFoundError(Exception):
    pass


class GastoCerradoError(Exception):
    pass


class GastoAuditUnavailableError(Exception):
    pass


def crear_gasto(categoria: str, descripcion: str, monto: int, usuario: str) -> Dict[str, Any]:
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


def editar_gasto(id_gasto: int, categoria: str, descripcion: str, monto: int, usuario: str) -> Dict[str, Any]:
    with db_conn() as conn:
        gasto = _leer_gasto_para_actualizar(conn, id_gasto)
        if gasto is None:
            raise GastoNotFoundError()
        if gasto.get("id_cierre") is not None:
            raise GastoCerradoError()
        _asegurar_auditoria_disponible(conn)

        actualizado = dict(gasto)
        actualizado.update({"categoria": categoria, "descripcion": descripcion, "monto": int(monto)})
        conn.execute(
            text("""
                UPDATE gastos_operacion
                SET categoria = :categoria, descripcion = :descripcion, monto = :monto
                WHERE id_gasto = :id_gasto AND id_cierre IS NULL
            """),
            {"id_gasto": id_gasto, "categoria": categoria, "descripcion": descripcion, "monto": int(monto)},
        )
        _auditar_gasto(conn, id_gasto, "EDITAR", usuario, gasto, actualizado)
        conn.commit()

    return _serialize_gasto(actualizado)


def eliminar_gasto(id_gasto: int, usuario: str) -> Dict[str, Any]:
    with db_conn() as conn:
        gasto = _leer_gasto_para_actualizar(conn, id_gasto)
        if gasto is None:
            raise GastoNotFoundError()
        if gasto.get("id_cierre") is not None:
            raise GastoCerradoError()
        _asegurar_auditoria_disponible(conn)

        conn.execute(
            text("""
                DELETE FROM gastos_operacion
                WHERE id_gasto = :id_gasto AND id_cierre IS NULL
            """),
            {"id_gasto": id_gasto},
        )
        _auditar_gasto(conn, id_gasto, "ELIMINAR", usuario, gasto, None)
        conn.commit()

    return {"ok": True, "id_gasto": id_gasto}


def _leer_gasto_para_actualizar(conn, id_gasto: int):
    row = conn.execute(
        text("""
            SELECT id_gasto, fecha_hora, categoria, descripcion, monto, usuario, id_cierre
            FROM gastos_operacion
            WHERE id_gasto = :id_gasto
            FOR UPDATE
        """),
        {"id_gasto": id_gasto},
    ).mappings().first()
    return dict(row) if row is not None else None


def _asegurar_auditoria_disponible(conn) -> None:
    try:
        conn.execute(text("SELECT 1 FROM gastos_operacion_auditoria LIMIT 1")).scalar()
    except Exception as exc:
        raise GastoAuditUnavailableError() from exc


def _auditar_gasto(conn, id_gasto: int, accion: str, usuario: str, anterior, nuevo) -> None:
    conn.execute(
        text("""
            INSERT INTO gastos_operacion_auditoria (
                id_gasto, accion, usuario, fecha_hora, snapshot_anterior, snapshot_nuevo
            )
            VALUES (:id_gasto, :accion, :usuario, :fecha_hora, :snapshot_anterior, :snapshot_nuevo)
        """),
        {
            "id_gasto": id_gasto,
            "accion": accion,
            "usuario": usuario,
            "fecha_hora": datetime.now(),
            "snapshot_anterior": _snapshot(anterior),
            "snapshot_nuevo": _snapshot(nuevo),
        },
    )


def _snapshot(value) -> str | None:
    if value is None:
        return None
    return json.dumps(_serialize_gasto(value), ensure_ascii=False, sort_keys=True)


def _serialize_gasto(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    fecha_hora = item.get("fecha_hora")
    item["fecha_hora"] = fecha_hora.isoformat() if hasattr(fecha_hora, "isoformat") else str(fecha_hora)
    item["id_gasto"] = int(item["id_gasto"])
    item["monto"] = int(item["monto"] or 0)
    item["id_cierre"] = int(item["id_cierre"]) if item.get("id_cierre") is not None else None
    return item
