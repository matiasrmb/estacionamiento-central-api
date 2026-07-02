from pydantic import BaseModel, Field


class WashVehicleTypeIn(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=50)
    nombre: str = Field(..., min_length=1, max_length=80)
    valor_lavado: int = Field(..., ge=0)
    activo: bool = True


class WashTypeIn(BaseModel):
    codigo: str = Field(..., min_length=1, max_length=50)
    nombre: str = Field(..., min_length=1, max_length=80)
    activo: bool = True


class WashPriceSnapshot(BaseModel):
    id_tipo_vehiculo_lavado: int
    tipo_vehiculo_lavado_snapshot: str
    valor_lavado_snapshot: int
