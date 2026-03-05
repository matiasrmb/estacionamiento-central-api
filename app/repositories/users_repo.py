from typing import Optional, Dict, Any
from sqlalchemy import text
from app.db.database import db_conn


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """
    Lee usuario desde MySQL.
    DB: usuarios( id_usuario, usuario, clave_hash, rol, activo )
    rol: 'administrador'|'operador'
    """
    query = """
        SELECT id_usuario, usuario, clave_hash, rol, activo
        FROM usuarios
        WHERE usuario = :username
        LIMIT 1
    """
    with db_conn() as conn:
        row = conn.execute(text(query), {"username": username}).mappings().first()
        return dict(row) if row else None