from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.operaciones_servicio_repo import (
    convertir_solo_lavado_a_estadia as repo_convertir_solo_lavado_a_estadia,
    finalizar_solo_lavado_cobrar as repo_finalizar_solo_lavado_cobrar,
    iniciar_solo_lavado as repo_iniciar_solo_lavado,
    list_solo_lavados_activos as repo_list_solo_lavados_activos,
)
from app.repositories.wash_pricing_repo import list_wash_vehicle_types as repo_list_wash_vehicle_types


router = APIRouter(prefix="/lavados/solo", tags=["lavados-solo"])


class SoloLavadoInicioIn(BaseModel):
    patente: str = Field(..., min_length=1, max_length=10)
    id_tipo_vehiculo_lavado: int = Field(..., ge=1)


def _handle_solo_lavado_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.post("", status_code=status.HTTP_201_CREATED)
def iniciar_solo_lavado(payload: SoloLavadoInicioIn, user=Depends(require_role("operador", "admin"))):
    try:
        return repo_iniciar_solo_lavado(
            payload.patente,
            payload.id_tipo_vehiculo_lavado,
            user.get("sub") or "",
        )
    except Exception as exc:
        _handle_solo_lavado_error(exc)


@router.get("")
def listar_solo_lavados_activos(
    patente: str | None = None,
    _user=Depends(require_role("operador", "admin")),
):
    return {"items": repo_list_solo_lavados_activos(patente)}


@router.get("/tipos-vehiculo")
def listar_tipos_vehiculo_para_solo_lavado(_user=Depends(require_role("operador", "admin"))):
    return {"items": [item for item in repo_list_wash_vehicle_types() if int(item.get("activo") or 0) == 1]}


@router.post("/{id_operacion_servicio}/cobrar")
def finalizar_solo_lavado_cobrar(
    id_operacion_servicio: int,
    user=Depends(require_role("operador", "admin")),
):
    try:
        return repo_finalizar_solo_lavado_cobrar(id_operacion_servicio, user.get("sub") or "")
    except Exception as exc:
        _handle_solo_lavado_error(exc)


@router.post("/{id_operacion_servicio}/convertir-estadia")
def convertir_solo_lavado_a_estadia(
    id_operacion_servicio: int,
    user=Depends(require_role("operador", "admin")),
):
    try:
        return repo_convertir_solo_lavado_a_estadia(id_operacion_servicio, user.get("sub") or "")
    except Exception as exc:
        _handle_solo_lavado_error(exc)
