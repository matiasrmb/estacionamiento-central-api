from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn


LAVADO_CATEGORIAS = {
    "lavado_citycar": "CityCar",
    "lavado_suv": "SUV",
    "lavado_camioneta": "Camioneta",
    "lavado_furgon": "Furgón",
    "lavado_minibus": "Mini bus o vehículos grandes",
}


def _get_config_int(conn, clave: str, default: int) -> int:
    row = conn.execute(
        text("SELECT valor FROM configuracion WHERE clave = :clave LIMIT 1"),
        {"clave": clave},
    ).fetchone()
    if not row:
        return default
    try:
        return int(float(row[0]))
    except Exception:
        return default


def list_lavado_categorias() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        return [
            {
                "clave": clave,
                "label": label,
                "valor": _get_config_int(conn, clave, 0),
            }
            for clave, label in LAVADO_CATEGORIAS.items()
        ]


def registrar_uso_bano(monto: int | None, usuario: str) -> Dict[str, Any]:
    now = datetime.now()
    with db_conn() as conn:
        valor = monto if monto is not None else _get_config_int(conn, "valor_bano", 300)
        conn.execute(
            text("""
                INSERT INTO usos_bano (fecha_hora, monto, usuario)
                VALUES (:fecha_hora, :monto, :usuario)
            """),
            {"fecha_hora": now, "monto": valor, "usuario": usuario},
        )
        conn.commit()
    return {"fecha_hora": now.isoformat(), "monto": int(valor), "usuario": usuario}


def iniciar_lavado(id_ingreso: int, categoria_lavado: str, usuario: str) -> Dict[str, Any]:
    if categoria_lavado not in LAVADO_CATEGORIAS:
        raise ValueError("INVALID_WASH_CATEGORY")

    now = datetime.now()
    with db_conn() as conn:
        ingreso = conn.execute(
            text("""
                SELECT i.id_ingreso, i.id_vehiculo, i.en_lavado, v.patente
                FROM ingresos i
                JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
                WHERE i.id_ingreso = :id_ingreso
                  AND i.fecha_hora_salida IS NULL
                LIMIT 1
            """),
            {"id_ingreso": id_ingreso},
        ).mappings().first()
        if not ingreso:
            raise LookupError("INGRESO_NOT_FOUND")
        if int(ingreso.get("en_lavado") or 0) == 1:
            raise RuntimeError("WASH_ALREADY_ACTIVE")

        valor = _get_config_int(conn, categoria_lavado, 0)
        conn.execute(
            text("""
                INSERT INTO lavados (
                    id_ingreso, id_vehiculo, patente, categoria_lavado,
                    valor_lavado, fecha_hora_inicio, usuario_inicio, estado
                )
                VALUES (
                    :id_ingreso, :id_vehiculo, :patente, :categoria_lavado,
                    :valor_lavado, :fecha_hora_inicio, :usuario_inicio, 'activo'
                )
            """),
            {
                "id_ingreso": id_ingreso,
                "id_vehiculo": ingreso["id_vehiculo"],
                "patente": ingreso["patente"],
                "categoria_lavado": categoria_lavado,
                "valor_lavado": valor,
                "fecha_hora_inicio": now,
                "usuario_inicio": usuario,
            },
        )
        id_lavado = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())
        conn.execute(text("UPDATE ingresos SET en_lavado = 1 WHERE id_ingreso = :id"), {"id": id_ingreso})
        conn.commit()
    return {"id_lavado": id_lavado, "id_ingreso": id_ingreso, "categoria_lavado": categoria_lavado, "valor_lavado": valor, "fecha_hora_inicio": now.isoformat()}


def finalizar_lavado(id_ingreso: int, usuario: str) -> Dict[str, Any]:
    now = datetime.now()
    with db_conn() as conn:
        lavado = conn.execute(
            text("""
                SELECT id_lavado, categoria_lavado, valor_lavado, fecha_hora_inicio
                FROM lavados
                WHERE id_ingreso = :id_ingreso
                  AND estado = 'activo'
                  AND fecha_hora_fin IS NULL
                ORDER BY fecha_hora_inicio DESC
                LIMIT 1
            """),
            {"id_ingreso": id_ingreso},
        ).mappings().first()
        if not lavado:
            raise LookupError("ACTIVE_WASH_NOT_FOUND")

        conn.execute(
            text("""
                UPDATE lavados
                SET fecha_hora_fin = :fecha_hora_fin,
                    usuario_fin = :usuario_fin,
                    estado = 'finalizado'
                WHERE id_lavado = :id_lavado
            """),
            {"fecha_hora_fin": now, "usuario_fin": usuario, "id_lavado": lavado["id_lavado"]},
        )
        conn.execute(text("UPDATE ingresos SET en_lavado = 0 WHERE id_ingreso = :id"), {"id": id_ingreso})
        conn.commit()
    return {"id_lavado": int(lavado["id_lavado"]), "id_ingreso": id_ingreso, "categoria_lavado": lavado["categoria_lavado"], "valor_lavado": int(lavado["valor_lavado"]), "fecha_hora_fin": now.isoformat()}
