from typing import Any, Dict, List, Optional
from sqlalchemy import text
from app.db.database import db_conn


def find_active_ingreso_by_plate(patente: str) -> Optional[Dict[str, Any]]:
    """
    Activo = fecha_hora_salida IS NULL y en_espera=0 (MVP).
    """
    patente = patente.strip().upper()
    query = """
      SELECT i.id_ingreso, i.id_vehiculo, i.fecha_hora_ingreso, i.fecha_hora_salida,
             i.tarifa_aplicada, i.en_espera, i.cerrado, i.reingresado, i.usuario,
             v.patente
      FROM ingresos i
      JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
      WHERE v.patente = :p
        AND i.fecha_hora_salida IS NULL
        AND i.en_espera = 0
      ORDER BY i.id_ingreso DESC
      LIMIT 1
    """
    with db_conn() as conn:
        row = conn.execute(text(query), {"p": patente}).mappings().first()
        return dict(row) if row else None


def create_ingreso(id_vehiculo: int, fecha_hora_ingreso, usuario: str) -> int:
    query = """
      INSERT INTO ingresos (id_vehiculo, fecha_hora_ingreso, usuario)
      VALUES (:idv, :fhi, :usr)
    """
    with db_conn() as conn:
        conn.execute(text(query), {"idv": id_vehiculo, "fhi": fecha_hora_ingreso, "usr": usuario})
        conn.commit()
        new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return int(new_id)


def list_activos(limit: int, offset: int, search: str | None) -> Dict[str, Any]:
    """
    Lista activos por fecha_hora_salida IS NULL y en_espera=0.
    """
    where_search = ""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if search:
        where_search = " AND v.patente LIKE :s "
        params["s"] = f"%{search.strip().upper()}%"

    base = f"""
      FROM ingresos i
      JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
      WHERE i.fecha_hora_salida IS NULL
        AND i.en_espera = 0
      {where_search}
    """

    query_items = f"""
      SELECT i.id_ingreso, v.patente, i.fecha_hora_ingreso
      {base}
      ORDER BY i.fecha_hora_ingreso DESC
      LIMIT :limit OFFSET :offset
    """

    query_total = f"SELECT COUNT(*) {base}"

    with db_conn() as conn:
        items = conn.execute(text(query_items), params).mappings().all()
        total = conn.execute(text(query_total), params).scalar()

    return {"items": [dict(x) for x in items], "total": int(total)}


def get_ingreso_by_id(id_ingreso: int) -> Optional[Dict[str, Any]]:
    query = """
      SELECT i.id_ingreso, i.id_vehiculo, i.fecha_hora_ingreso, i.fecha_hora_salida,
             i.tarifa_aplicada, i.en_espera, i.cerrado, i.reingresado, i.usuario,
             v.patente
      FROM ingresos i
      JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
      WHERE i.id_ingreso = :id
      LIMIT 1
    """
    with db_conn() as conn:
        row = conn.execute(text(query), {"id": id_ingreso}).mappings().first()
        return dict(row) if row else None


def confirm_salida(id_ingreso: int, fecha_hora_salida, tarifa_aplicada: float) -> None:
    query = """
      UPDATE ingresos
      SET fecha_hora_salida = :fhs,
          tarifa_aplicada = :tar
      WHERE id_ingreso = :id
        AND fecha_hora_salida IS NULL
    """
    with db_conn() as conn:
        res = conn.execute(text(query), {"fhs": fecha_hora_salida, "tar": tarifa_aplicada, "id": id_ingreso})
        conn.commit()
        if res.rowcount != 1:
            # No actualizó: ya tenía salida o no existía
            raise RuntimeError("INGRESO_NOT_ACTIVE")