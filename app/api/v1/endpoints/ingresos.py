from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.core.plates import require_valid_plate
from app.repositories.ingresos_repo import (
    ActiveIngresoAlreadyExists,
    NochesNotAvailable,
    RequiredPrintJobCreationFailed,
    create_ingreso_with_required_pc_pdf_job,
    create_ingreso_with_noches_prepaid_and_required_pc_pdf_job,
)
from app.services.tickets_service import build_ticket_ingreso_payload

router = APIRouter()


class IngresoRequest(BaseModel):
    patente: str = Field(..., min_length=3, max_length=12)
    origen: str | None = Field(default="MOBILE", max_length=20)
    noches_prepagadas: bool = False


@router.post("/ingresos", tags=["mvp"])
def registrar_ingreso(payload: IngresoRequest, user=Depends(require_role("operador", "admin"))):
    try:
        patente = require_valid_plate(payload.patente)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    now = datetime.now()  # hora servidor local
    hora_ingreso_iso = now.isoformat(timespec="seconds")

    try:
        if payload.noches_prepagadas:
            created = create_ingreso_with_noches_prepaid_and_required_pc_pdf_job(
                patente=patente,
                fecha_hora_ingreso=now,
                usuario=user.get("sub"),
                build_ticket_payload=lambda id_ingreso, cobro_noche: build_ticket_ingreso_payload(
                    id_ingreso=id_ingreso,
                    patente=patente,
                    hora_ingreso_iso=hora_ingreso_iso,
                    usuario_claims=user,
                    server_time_iso=hora_ingreso_iso,
                    cobro_noche=cobro_noche,
                ),
            )
        else:
            created = create_ingreso_with_required_pc_pdf_job(
                patente=patente,
                fecha_hora_ingreso=now,
                usuario=user.get("sub"),
                build_ticket_payload=lambda id_ingreso: build_ticket_ingreso_payload(
                    id_ingreso=id_ingreso,
                    patente=patente,
                    hora_ingreso_iso=hora_ingreso_iso,
                    usuario_claims=user,
                    server_time_iso=hora_ingreso_iso,
                ),
            )
    except ActiveIngresoAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "PLATE_ALREADY_ACTIVE",
                    "message": "La patente ya tiene un ingreso activo",
                    "details": {"patente": patente},
                }
            },
        )
    except RequiredPrintJobCreationFailed:
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "PRINT_JOB_CREATE_FAILED", "message": "No se pudo crear el trabajo de impresión PC"}},
        )
    except NochesNotAvailable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "NOCHES_NOT_AVAILABLE", "message": "Noches no está disponible para este ingreso"}},
        )

    id_ingreso = created["id_ingreso"]
    return {
        "ingreso": {
            "id_ingreso": id_ingreso,
            "patente": patente,
            "hora_ingreso": hora_ingreso_iso,
            "estado": "ACTIVO",
        },
        "print": {
            "pc_job_created": True,
            "pc_job_id": created["pc_job_id"],
            "sunmi_payload": {"enabled": False, "text": None},
        },
        "noches": created.get("cobro_noche"),
    }
