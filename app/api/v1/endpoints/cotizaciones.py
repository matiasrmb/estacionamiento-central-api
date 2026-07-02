from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.services.cotizaciones import preview_cotizacion as service_preview_cotizacion


router = APIRouter(prefix="/cotizaciones", tags=["cotizaciones"])


class EstadiaQuoteIn(BaseModel):
    minutos: int = Field(..., ge=0)
    monto_estadia: int = Field(..., ge=0)
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
    return payload.model_dump(exclude_none=True)


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
