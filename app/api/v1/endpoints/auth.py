import logging
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.core.security import verify_password, create_access_token
from app.repositories.asistencias_repo import registrar_asistencia_inicio, registrar_asistencia_salida
from app.repositories.users_repo import get_user_by_username

router = APIRouter()
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    usuario: str = Field(..., min_length=1, max_length=50)
    clave: str = Field(..., min_length=1, max_length=200)
    device_id: str | None = Field(default=None, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: str
    rol: str  # 'admin'|'operador'


def _map_rol_db_to_api(rol_db: str) -> str:
    if rol_db == "administrador":
        return "admin"
    return "operador"


@router.post("/auth/login", response_model=LoginResponse, tags=["auth"])
def login(payload: LoginRequest):
    user = get_user_by_username(payload.usuario)
    if not user or int(user.get("activo", 0)) != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Credenciales inválidas"}},
        )

    if not verify_password(payload.clave, user["clave_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Credenciales inválidas"}},
        )

    rol_api = _map_rol_db_to_api(user["rol"])
    session_id = uuid4().hex
    device_id = (payload.device_id or f"legacy-{session_id}").strip()
    if not device_id:
        device_id = f"legacy-{session_id}"
    registrar_asistencia_inicio(user["usuario"], device_id, session_id)

    token = create_access_token(
        subject=user["usuario"],
        extra_claims={
            "rol": rol_api,          # rol normalizado para la API
            "rol_db": user["rol"],   # opcional: útil para auditoría
            "id_usuario": user["id_usuario"],
            "sid": session_id,
            "device_id": device_id,
        },
    )

    return LoginResponse(
        access_token=token,
        usuario=user["usuario"],
        rol=rol_api,
    )


@router.post("/auth/logout", tags=["auth"])
def logout(user=Depends(require_role("operador", "admin"))):
    resumen = registrar_asistencia_salida(user.get("sub") or "", user.get("sid") or "")
    return {"ok": True, "resumen": resumen}
