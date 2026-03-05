from typing import Optional, Dict, Any
from sqlalchemy import text
from app.db.database import db_conn


def get_or_create_vehicle_by_plate(patente: str) -> int:
    """
    Busca vehículo por patente. Si no existe, lo crea como 'ocasional'.
    Retorna id_vehiculo.
    """
    patente = patente.strip().upper()

    with db_conn() as conn:
        row = conn.execute(
            text("SELECT id_vehiculo FROM vehiculos WHERE patente = :p LIMIT 1"),
            {"p": patente},
        ).mappings().first()

        if row:
            return int(row["id_vehiculo"])

        # Crear
        conn.execute(
            text("INSERT INTO vehiculos (patente, tipo_cliente, activo) VALUES (:p, 'ocasional', 1)"),
            {"p": patente},
        )
        conn.commit()

        new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return int(new_id)


def get_vehicle_by_id(id_vehiculo: int) -> Optional[Dict[str, Any]]:
    with db_conn() as conn:
        row = conn.execute(
            text("SELECT id_vehiculo, patente, tipo_cliente, activo, tarifa_mensual FROM vehiculos WHERE id_vehiculo = :id"),
            {"id": id_vehiculo},
        ).mappings().first()
        return dict(row) if row else None