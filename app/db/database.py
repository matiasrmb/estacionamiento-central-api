import logging
import time
from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy import create_engine, text
try:
    from sqlalchemy import event
except ImportError:
    event = None
from sqlalchemy.engine import Engine, Connection

from app.core.config import settings
from app.core.slowlog import log_if_slow

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


def _statement_operation(statement: str) -> str:
    return (statement or "").strip().split(maxsplit=1)[0].upper() or "SQL"


if event is not None:
    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._slowlog_started = time.perf_counter()


    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        started = getattr(context, "_slowlog_started", None)
        if started is None:
            return
        duration_ms = (time.perf_counter() - started) * 1000
        log_if_slow(
            logger,
            threshold_env="SLOW_API_DB_MS",
            default_ms=500,
            area="api_db",
            operation=_statement_operation(statement),
            duration_ms=duration_ms,
            context={"executemany": executemany},
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
