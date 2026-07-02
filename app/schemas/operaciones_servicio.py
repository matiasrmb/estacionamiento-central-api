from enum import Enum
from typing import Optional

from pydantic import BaseModel


class OperacionServicioState(str, Enum):
    ACTIVO = "ACTIVO"
    FINALIZADO_COBRADO = "FINALIZADO_COBRADO"
    CONVERTIDO_ESTADIA = "CONVERTIDO_ESTADIA"


class OperacionServicioContrato(BaseModel):
    patente: str
    id_tipo_vehiculo_lavado: int
    tipo_vehiculo_lavado_snapshot: str
    valor_lavado_snapshot: int
    fecha_hora_inicio: str
    fecha_hora_fin: Optional[str] = None
    usuario_inicio: str
    usuario_fin: Optional[str] = None
    estado: OperacionServicioState
    id_ingreso_generado: Optional[int] = None
    cobra_ahora: bool = False
