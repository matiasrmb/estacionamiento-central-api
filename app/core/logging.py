import logging
import os
from logging.handlers import RotatingFileHandler

from app.core.config import settings


def setup_logging() -> None:
    """
    Configura logging con salida a consola y archivo rotativo.

    - Consola: útil para desarrollo.
    - Archivo: útil para diagnóstico en producción (LAN).
    """
    logger = logging.getLogger()
    logger.setLevel(settings.log_level.upper())

    # Evitar duplicación de handlers si uvicorn recarga
    if logger.handlers:
        return

    log_format = (
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    formatter = logging.Formatter(log_format)

    # Consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Archivo rotativo
    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        filename="logs/api.log",
        maxBytes=2_000_000,  # ~2MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logging.getLogger("uvicorn.access").propagate = True