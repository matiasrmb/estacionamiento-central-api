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


def delete_user_safely(usuario: str, current_usuario: str | None = None) -> Dict[str, Any]:
    usuario = usuario.strip()
    current_usuario = (current_usuario or "").strip()
    if not usuario:
        raise ValueError("INVALID_USER_DATA")

    with db_conn() as conn:
        user = conn.execute(
            text("""
                SELECT usuario, rol, activo
                FROM usuarios
                WHERE usuario = :usuario
                LIMIT 1
            """),
            {"usuario": usuario},
        ).mappings().first()
        if not user:
            raise LookupError("USER_NOT_FOUND")

        if current_usuario and usuario.lower() == current_usuario.lower():
            raise PermissionError("CANNOT_DELETE_CURRENT_USER")

        if user["rol"] == "administrador" and int(user.get("activo", 0)) == 1:
            active_admins_after_delete = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM usuarios
                    WHERE rol = 'administrador'
                      AND activo = 1
                      AND usuario <> :usuario
                """),
                {"usuario": usuario},
            ).scalar()
            if int(active_admins_after_delete or 0) == 0:
                raise PermissionError("CANNOT_DELETE_LAST_ADMIN")

        if _user_has_activity(conn, usuario):
            conn.execute(
                text("UPDATE usuarios SET activo = 0 WHERE usuario = :usuario"),
                {"usuario": usuario},
            )
            conn.commit()
            return {"ok": True, "action": "deactivated", "message": "USER_DEACTIVATED_HISTORY_PRESERVED"}

        result = conn.execute(
            text("DELETE FROM usuarios WHERE usuario = :usuario"),
            {"usuario": usuario},
        )
        if result.rowcount == 0:
            raise LookupError("USER_NOT_FOUND")
        conn.commit()
        return {"ok": True, "action": "deleted", "message": "USER_DELETED"}


def _user_has_activity(conn, usuario: str) -> bool:
    required_activity_queries = [
        "SELECT 1 AS found FROM ingresos WHERE usuario = :usuario LIMIT 1",
        "SELECT 1 AS found FROM lavados WHERE usuario_inicio = :usuario OR usuario_fin = :usuario LIMIT 1",
        "SELECT 1 AS found FROM usos_bano WHERE usuario = :usuario LIMIT 1",
        "SELECT 1 AS found FROM cierres_diarios WHERE usuario = :usuario LIMIT 1",
        "SELECT 1 AS found FROM asistencias WHERE usuario = :usuario LIMIT 1",
    ]
    optional_activity_queries = [
        ("operaciones_servicio", "SELECT 1 AS found FROM operaciones_servicio WHERE usuario_inicio = :usuario OR usuario_fin = :usuario LIMIT 1"),
        ("ingresos_eliminados", "SELECT 1 AS found FROM ingresos_eliminados WHERE usuario_eliminador = :usuario LIMIT 1"),
        ("print_jobs", "SELECT 1 AS found FROM print_jobs WHERE JSON_SEARCH(payload_json, 'one', :usuario) IS NOT NULL LIMIT 1"),
    ]

    for query in required_activity_queries:
        if conn.execute(text(query), {"usuario": usuario}).mappings().first():
            return True

    for table, query in optional_activity_queries:
        try:
            result = conn.execute(text(query), {"usuario": usuario}).mappings().first()
        except Exception as exc:
            if _is_missing_table_error(exc):
                print(f"Optional table '{table}' not found while checking user activity; skipping.")
                continue
            raise
        if result:
            return True
    return False


def _is_missing_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "doesn't exist" in message or "no existe" in message or "unknown table" in message


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
