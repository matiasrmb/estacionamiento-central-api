from typing import Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.configuracion_repo import get_all_config, upsert_config_values


router = APIRouter(prefix="/configuracion", tags=["configuracion"])


class ConfiguracionUpdateIn(BaseModel):
    valores: Dict[str, str] = Field(default_factory=dict)


@router.get("")
def obtener_configuracion(_user=Depends(require_role("admin"))):
    return {"items": get_all_config()}


@router.put("")
def actualizar_configuracion(payload: ConfiguracionUpdateIn, _user=Depends(require_role("admin"))):
    upsert_config_values(payload.valores)
    return {"ok": True, "items": get_all_config()}
