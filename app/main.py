import logging
import time
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException as FastAPIHTTPException

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.slowlog import log_if_slow
from app.core.errors import (
    validation_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
)
from app.api.v1.router import api_router
from app.db.schema_ensure import (
    ensure_asistencias_schema,
    ensure_gastos_operacion_schema,
    ensure_monthly_payments_schema,
    ensure_noches_schema,
    ensure_operaciones_servicio_schema,
    ensure_wash_vehicle_type_schema,
)

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def slow_request_logging(request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        log_if_slow(
            logger,
            threshold_env="SLOW_API_REQUEST_MS",
            default_ms=1000,
            area="api",
            operation="request",
            duration_ms=duration_ms,
            context={
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
            },
        )

# Router versionado
app.include_router(api_router, prefix="/api/v1")

# Handlers de errores (formato estándar)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(FastAPIHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Starting %s (env=%s)", settings.app_name, settings.env)
    settings.validate_runtime_safety()
    ensure_asistencias_schema()
    try:
        ensure_wash_vehicle_type_schema()
        ensure_operaciones_servicio_schema()
    except Exception:
        logger.exception("Could not ensure Solo lavado schema at startup")
    ensure_gastos_operacion_schema()
    ensure_monthly_payments_schema()
    ensure_noches_schema()
