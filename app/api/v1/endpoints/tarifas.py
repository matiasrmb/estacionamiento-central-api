from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.tarifas_repo import (
    create_tarifa_personalizada as repo_create_tarifa_personalizada,
    delete_tarifa_personalizada as repo_delete_tarifa_personalizada,
    list_tarifas_personalizadas,
    update_tarifa_personalizada as repo_update_tarifa_personalizada,
)


router = APIRouter(prefix="/tarifas", tags=["tarifas"])


class TarifaPersonalizadaIn(BaseModel):
    minuto_inicio: int = Field(..., ge=0)
    minuto_fin: int = Field(..., ge=0)
    valor: int = Field(..., ge=0)


def _handle_tarifa_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TARIFA_NOT_FOUND")
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.get("/personalizadas")
def listar_tarifas_personalizadas(_user=Depends(require_role("admin"))):
    return {"items": list_tarifas_personalizadas()}


@router.post("/personalizadas", status_code=status.HTTP_201_CREATED)
def crear_tarifa_personalizada(payload: TarifaPersonalizadaIn, _user=Depends(require_role("admin"))):
    try:
        id_tarifa = repo_create_tarifa_personalizada(
            minuto_inicio=payload.minuto_inicio,
            minuto_fin=payload.minuto_fin,
            valor=payload.valor,
        )
    except Exception as exc:
        _handle_tarifa_error(exc)
    return {"id_tarifa": id_tarifa}


@router.put("/personalizadas/{id_tarifa}")
def actualizar_tarifa_personalizada(
    id_tarifa: int,
    payload: TarifaPersonalizadaIn,
    _user=Depends(require_role("admin")),
):
    try:
        repo_update_tarifa_personalizada(
            id_tarifa=id_tarifa,
            minuto_inicio=payload.minuto_inicio,
            minuto_fin=payload.minuto_fin,
            valor=payload.valor,
        )
    except Exception as exc:
        _handle_tarifa_error(exc)
    return {"ok": True}


@router.delete("/personalizadas/{id_tarifa}")
def eliminar_tarifa_personalizada(id_tarifa: int, _user=Depends(require_role("admin"))):
    try:
        repo_delete_tarifa_personalizada(id_tarifa)
    except Exception as exc:
        _handle_tarifa_error(exc)
    return {"ok": True}
