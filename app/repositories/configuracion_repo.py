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