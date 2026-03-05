import logging
from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, Connection

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_db_url() -> str:
    """
    Construye URL SQLAlchemy para MySQL usando PyMySQL.
    """
    # Nota: si db_password está vacío, esto aún funciona.
    return (
        f"mysql+pymysql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
        f"?charset=utf8mb4"
    )


engine: Engine = create_engine(
    _build_db_url(),
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,  # detecta conexiones muertas
    future=True,
)


@contextmanager
def db_conn() -> Generator[Connection, None, None]:
    """
    Context manager para obtener una conexión y cerrarla correctamente.
    """
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()


def scalar(query: str, **params: Any) -> Any:
    """
    Ejecuta un SELECT escalar y retorna el primer valor.
    """
    with db_conn() as conn:
        result = conn.execute(text(query), params)
        return result.scalar()


def execute(query: str, **params: Any) -> int:
    """
    Ejecuta INSERT/UPDATE/DELETE. Retorna filas afectadas.
    """
    with db_conn() as conn:
        result = conn.execute(text(query), params)
        conn.commit()
        return result.rowcount