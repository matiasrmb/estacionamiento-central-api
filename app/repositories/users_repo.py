from typing import Optional, Dict, Any, List
from sqlalchemy import text

from app.core.security import pwd_context
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


def list_users() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT id_usuario, usuario, rol, activo
                FROM usuarios
                ORDER BY id_usuario ASC
            """)
        ).mappings().all()
    return [_serialize_user(row) for row in rows]


def create_user(usuario: str, clave: str, rol: str) -> int:
    usuario = usuario.strip()
    rol_db = _api_role_to_db(rol)
    if not usuario or not clave:
        raise ValueError("INVALID_USER_DATA")

    clave_hash = pwd_context.hash(clave)
    with db_conn() as conn:
        existing = conn.execute(
            text("SELECT id_usuario FROM usuarios WHERE usuario = :usuario LIMIT 1"),
            {"usuario": usuario},
        ).fetchone()
        if existing:
            raise RuntimeError("USER_ALREADY_EXISTS")

        conn.execute(
            text("""
                INSERT INTO usuarios (usuario, clave_hash, rol, activo)
                VALUES (:usuario, :clave_hash, :rol, 1)
            """),
            {"usuario": usuario, "clave_hash": clave_hash, "rol": rol_db},
        )
        id_usuario = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())
        conn.commit()
    return id_usuario


def update_user_password(usuario: str, clave: str) -> None:
    if not usuario.strip() or not clave:
        raise ValueError("INVALID_USER_DATA")
    clave_hash = pwd_context.hash(clave)
    with db_conn() as conn:
        result = conn.execute(
            text("UPDATE usuarios SET clave_hash = :clave_hash WHERE usuario = :usuario"),
            {"clave_hash": clave_hash, "usuario": usuario.strip()},
        )
        if result.rowcount == 0:
            raise LookupError("USER_NOT_FOUND")
        conn.commit()


def update_user_status(usuario: str, activo: bool) -> None:
    with db_conn() as conn:
        result = conn.execute(
            text("UPDATE usuarios SET activo = :activo WHERE usuario = :usuario"),
            {"activo": 1 if activo else 0, "usuario": usuario.strip()},
        )
        if result.rowcount == 0:
            raise LookupError("USER_NOT_FOUND")
        conn.commit()


def _serialize_user(row) -> Dict[str, Any]:
    return {
        "id_usuario": int(row["id_usuario"]),
        "usuario": row["usuario"],
        "rol": _db_role_to_api(row["rol"]),
        "rol_db": row["rol"],
        "activo": bool(row["activo"]),
    }


def _db_role_to_api(rol: str) -> str:
    return "admin" if rol == "administrador" else "operador"


def _api_role_to_db(rol: str) -> str:
    normalized = rol.strip().lower()
    if normalized in {"admin", "administrador"}:
        return "administrador"
    if normalized == "operador":
        return "operador"
    raise ValueError("INVALID_ROLE")
