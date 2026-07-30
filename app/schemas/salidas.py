from pydantic import BaseModel, Field


class NochePrepagadaOut(BaseModel):
    monto_snapshot: int
    hora_inicio_snapshot: str
    hora_fin_snapshot: str


class SalidaPreviewIn(BaseModel):
    id_ingreso: int = Field(..., ge=1)


class SalidaPreviewOut(BaseModel):
    id_ingreso: int
    patente: str
    minutos: int
    monto: int
    a_cobrar_ahora: int
    detalle: str
    noches_prepagadas: list[NochePrepagadaOut] = Field(default_factory=list)
    total_noches_prepagadas: int = 0


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
    a_cobrar_ahora: int
    fecha_hora_ingreso: str
    fecha_hora_salida: str
    detalle: str
    monto_estacionamiento: int
    total_lavados: int
    noches_prepagadas: list[NochePrepagadaOut] = Field(default_factory=list)
    total_noches_prepagadas: int = 0
    print_jobs_creados: int
