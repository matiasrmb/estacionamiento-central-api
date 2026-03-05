import logging
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException as FastAPIHTTPException

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.errors import (
    validation_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
)
from app.api.v1.router import api_router

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)

# Router versionado
app.include_router(api_router, prefix="/api/v1")

# Handlers de errores (formato estándar)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(FastAPIHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Starting %s (env=%s)", settings.app_name, settings.env)