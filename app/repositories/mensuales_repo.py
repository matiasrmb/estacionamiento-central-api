from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn


def list_mensuales() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT id_vehiculo, patente, tarifa_mensual
                FROM vehiculos
                WHERE tipo_cliente = 'mensual'
                  AND activo = 1
                ORDER BY patente ASC
            """)
        ).mappings().all()
    return [dict(row) for row in rows]


def upsert_mensual(patente: str, tarifa_mensual: int | None = None) -> int:
    patente = patente.strip().upper()
    if not patente:
        raise ValueError("INVALID_PLATE")

    with db_conn() as conn:
        row = conn.execute(
            text("SELECT id_vehiculo FROM vehiculos WHERE patente = :patente LIMIT 1"),
            {"patente": patente},
        ).mappings().first()

        if row:
            id_vehiculo = int(row["id_vehiculo"])
            conn.execute(
                text("""
                    UPDATE vehiculos
                    SET tipo_cliente = 'mensual',
                        activo = 1,
                        tarifa_mensual = COALESCE(:tarifa_mensual, tarifa_mensual)
                    WHERE id_vehiculo = :id_vehiculo
                """),
                {"id_vehiculo": id_vehiculo, "tarifa_mensual": tarifa_mensual},
            )
        else:
            conn.execute(
                text("""
                    INSERT INTO vehiculos (patente, tipo_cliente, activo, tarifa_mensual)
                    VALUES (:patente, 'mensual', 1, :tarifa_mensual)
                """),
                {"patente": patente, "tarifa_mensual": tarifa_mensual},
            )
            id_vehiculo = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())

        conn.commit()
        return id_vehiculo


def update_tarifa_mensual(id_vehiculo: int, tarifa_mensual: int) -> None:
    with db_conn() as conn:
        result = conn.execute(
            text("""
                UPDATE vehiculos
                SET tarifa_mensual = :tarifa_mensual
                WHERE id_vehiculo = :id_vehiculo
                  AND tipo_cliente = 'mensual'
                  AND activo = 1
            """),
            {"id_vehiculo": id_vehiculo, "tarifa_mensual": tarifa_mensual},
        )
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("MENSUAL_NOT_FOUND")


def deactivate_mensual(id_vehiculo: int) -> None:
    with db_conn() as conn:
        result = conn.execute(
            text("""
                UPDATE vehiculos
                SET activo = 0
                WHERE id_vehiculo = :id_vehiculo
                  AND tipo_cliente = 'mensual'
            """),
            {"id_vehiculo": id_vehiculo},
        )
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("MENSUAL_NOT_FOUND")
