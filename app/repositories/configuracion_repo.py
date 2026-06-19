from typing import Dict
from sqlalchemy import text
from app.db.database import db_conn


def get_all_config() -> Dict[str, str]:
    """
    Lee tabla configuracion(clave, valor) a dict.
    """
    with db_conn() as conn:
        rows = conn.execute(text("SELECT clave, valor FROM configuracion")).mappings().all()
    return {str(r["clave"]): str(r["valor"]) for r in rows}


def upsert_config_values(values: Dict[str, str]) -> None:
    """
    Inserta o actualiza claves de configuración.
    """
    query = text("""
        INSERT INTO configuracion (clave, valor)
        VALUES (:clave, :valor)
        ON DUPLICATE KEY UPDATE valor = VALUES(valor)
    """)
    with db_conn() as conn:
        for clave, valor in values.items():
            conn.execute(query, {"clave": clave, "valor": str(valor)})
        conn.commit()
