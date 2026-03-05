from typing import Any, Dict, Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    payload: Dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Normaliza los 422 de FastAPI al formato estándar
    return error_response(
        status_code=422,
        code="UNPROCESSABLE_ENTITY",
        message="Validación fallida",
        details={"errors": exc.errors()},
    )


def http_exception_handler(_: Request, exc) -> JSONResponse:
    # exc es fastapi.HTTPException
    detail = exc.detail
    # Permite que detail venga ya en formato {"error":{...}} o como string
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)

    return error_response(
        status_code=exc.status_code,
        code="HTTP_ERROR",
        message=str(detail),
    )


def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="Error interno",
        details={"type": exc.__class__.__name__},
    )