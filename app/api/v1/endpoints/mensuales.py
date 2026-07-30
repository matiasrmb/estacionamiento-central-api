from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.mensuales_repo import (
    deactivate_mensual,
    list_mensuales,
    register_monthly_payment,
    update_mensual_config,
    update_tarifa_mensual,
    upsert_mensual,
)


router = APIRouter(prefix="/mensuales", tags=["mensuales"])


class MensualIn(BaseModel):
    patente: str = Field(..., min_length=3, max_length=12)
    tarifa_mensual: int | None = Field(default=None, ge=0)
    dia_vencimiento: int | None = Field(default=None, ge=1, le=31)
    telefono: str | None = Field(default=None, max_length=30)


class TarifaMensualIn(BaseModel):
    tarifa_mensual: int = Field(..., ge=0)


class MensualConfigIn(BaseModel):
    tarifa_mensual: int = Field(..., ge=0)
    dia_vencimiento: int = Field(..., ge=1, le=31)
    telefono: str | None = Field(default=None, max_length=30)


class PagoMensualIn(BaseModel):
    metodo_pago: str | None = Field(default=None, max_length=40)
    observacion: str | None = Field(default=None, max_length=500)


@router.get("")
def listar_mensuales(_user=Depends(require_role("admin", "operador"))):
    return {"items": list_mensuales()}


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_mensual(payload: MensualIn, _user=Depends(require_role("admin", "operador"))):
    try:
        id_vehiculo = upsert_mensual(
            payload.patente,
            payload.tarifa_mensual,
            payload.dia_vencimiento,
            payload.telefono,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return {"id_vehiculo": id_vehiculo}


@router.put("/{id_vehiculo}/tarifa")
def actualizar_tarifa_mensual(
    id_vehiculo: int,
    payload: TarifaMensualIn,
    _user=Depends(require_role("admin", "operador")),
):
    try:
        update_tarifa_mensual(id_vehiculo, payload.tarifa_mensual)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MENSUAL_NOT_FOUND")
    return {"ok": True}


@router.put("/{id_vehiculo}")
def actualizar_mensual(
    id_vehiculo: int,
    payload: MensualConfigIn,
    _user=Depends(require_role("admin", "operador")),
):
    try:
        update_mensual_config(
            id_vehiculo,
            payload.tarifa_mensual,
            payload.dia_vencimiento,
            payload.telefono,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MENSUAL_NOT_FOUND")
    return {"ok": True}


@router.post("/{id_vehiculo}/pagos", status_code=status.HTTP_201_CREATED)
def registrar_pago_mensual(
    id_vehiculo: int,
    payload: PagoMensualIn,
    user=Depends(require_role("admin", "operador")),
):
    try:
        return register_monthly_payment(
            id_vehiculo=id_vehiculo,
            usuario=user.get("sub") or "",
            metodo_pago=payload.metodo_pago,
            observacion=payload.observacion,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MENSUAL_NOT_FOUND")
    except ValueError as exc:
        code = str(exc)
        if code == "MONTHLY_PAYMENT_ALREADY_EXISTS":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=code)


@router.delete("/{id_vehiculo}")
def eliminar_mensual(id_vehiculo: int, _user=Depends(require_role("admin", "operador"))):
    try:
        deactivate_mensual(id_vehiculo)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MENSUAL_NOT_FOUND")
    return {"ok": True}
