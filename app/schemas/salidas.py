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
    imprimir_sunmi: bool = Field(
        False,
        description="Deprecated and ignored. Exit receipts are queued only as PC_PDF print jobs.",
        deprecated=True,
    )


class SalidaConfirmOut(BaseModel):
    id_ingreso: int
    patente: str
    minutos: int
    monto: int
    fecha_hora_ingreso: str
    fecha_hora_salida: str
    detalle: str
    monto_estacionamiento: int
    total_lavados: int
    print_jobs_creados: int
