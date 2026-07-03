from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.wash_pricing_repo import list_wash_vehicle_types_for_quotes
from app.services.cotizaciones import preview_cotizacion as service_preview_cotizacion
from app.services.tarifas_service import calcular_monto_preview


router = APIRouter(prefix="/cotizaciones", tags=["cotizaciones"])


class EstadiaQuoteIn(BaseModel):
    minutos: int = Field(..., ge=0)
    monto_estadia: Optional[int] = Field(default=None, ge=0)
    tamano_vehiculo: Optional[str] = None


class LavadoQuoteIn(BaseModel):
    tipo_lavado: Optional[str] = None
    monto_lavado: int = Field(..., ge=0)


class VehiculoMensualQuoteIn(BaseModel):
    patente: Optional[str] = None
    monto_mensual: Optional[int] = Field(default=None, ge=0)
    monto_configurado: Optional[int] = Field(default=None, ge=0)
    monto_mensual_default: Optional[int] = Field(default=None, ge=0)


class MensualidadQuoteIn(BaseModel):
    vehiculos: List[VehiculoMensualQuoteIn] = Field(default_factory=list)


class CotizacionPreviewIn(BaseModel):
    estadia: Optional[EstadiaQuoteIn] = None
    lavado: Optional[LavadoQuoteIn] = None
    mensualidad: Optional[MensualidadQuoteIn] = None


def _to_payload(payload: CotizacionPreviewIn) -> Dict[str, Any]:
    data = payload.model_dump(exclude_none=True)
    estadia = data.get("estadia")
    if estadia is not None and "monto_estadia" not in estadia:
        now = datetime.now()
        preview = calcular_monto_preview(
            now - timedelta(minutes=int(estadia.get("minutos") or 0)),
            now,
        )
        estadia["monto_estadia"] = int(preview["monto"])
        estadia["detalle_tarifa"] = preview.get("detalle")
    return data


@router.get("/opciones")
def opciones_cotizacion(_user=Depends(require_role("operador", "admin"))):
    lavados = [
        item for item in list_wash_vehicle_types_for_quotes()
        if int(item.get("activo") or 0)
    ]
    return {
        "lavados": lavados,
        "mensualidades": [],
        "mensualidad_manual": True,
        "messages": {
            "lavados": None if lavados else "No hay precios de lavado configurados para cotizar.",
            "mensualidades": "Ingresá el monto mensual negociado manualmente.",
        },
    }


@router.post("/preview")
def preview_cotizacion(payload: CotizacionPreviewIn, _user=Depends(require_role("operador", "admin"))):
    try:
        return service_preview_cotizacion(_to_payload(payload))
    except ValueError as exc:
        if str(exc) == "MONTHLY_AMOUNT_REQUIRED":
            raise HTTPException(
                status_code=422,
                detail="MONTHLY_AMOUNT_REQUIRED",
            )
        raise
