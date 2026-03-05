from pydantic import BaseModel, Field


class SalidaPreviewIn(BaseModel):
    id_ingreso: int = Field(..., ge=1)


class SalidaPreviewOut(BaseModel):
    id_ingreso: int
    patente: str
    minutos: int
    monto: int
    detalle: str


class SalidaConfirmIn(BaseModel):
    id_ingreso: int = Field(..., ge=1)
    imprimir_sunmi: bool = False


class SalidaConfirmOut(BaseModel):
    id_ingreso: int
    patente: str
    minutos: int
    monto: int
    fecha_hora_salida: str
    print_jobs_creados: int