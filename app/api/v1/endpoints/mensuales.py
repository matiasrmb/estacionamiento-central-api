from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.mensuales_repo import (
    deactivate_mensual,
    list_mensuales,
    update_tarifa_mensual,
    upsert_mensual,
)


router = APIRouter(prefix="/mensuales", tags=["mensuales"])


class MensualIn(BaseModel):
    patente: str = Field(..., min_length=3, max_length=12)
    tarifa_mensual: int | None = Field(default=None, ge=0)


class TarifaMensualIn(BaseModel):
    tarifa_mensual: int = Field(..., ge=0)


@router.get("")
def listar_mensuales(_user=Depends(require_role("admin"))):
    return {"items": list_mensuales()}


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_mensual(payload: MensualIn, _user=Depends(require_role("admin"))):
    try:
        id_vehiculo = upsert_mensual(payload.patente, payload.tarifa_mensual)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return {"id_vehiculo": id_vehiculo}


@router.put("/{id_vehiculo}/tarifa")
def actualizar_tarifa_mensual(
    id_vehiculo: int,
    payload: TarifaMensualIn,
    _user=Depends(require_role("admin")),
):
    try:
        update_tarifa_mensual(id_vehiculo, payload.tarifa_mensual)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MENSUAL_NOT_FOUND")
    return {"ok": True}


@router.delete("/{id_vehiculo}")
def eliminar_mensual(id_vehiculo: int, _user=Depends(require_role("admin"))):
    try:
        deactivate_mensual(id_vehiculo)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MENSUAL_NOT_FOUND")
    return {"ok": True}
