from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.ingresos_repo import find_active_ingreso_by_plate, create_ingreso
from app.repositories.vehiculos_repo import get_or_create_vehicle_by_plate
from app.repositories.print_jobs_repo import create_print_job_pc_pdf
from app.services.tickets_service import build_ticket_ingreso_payload

router = APIRouter()


class IngresoRequest(BaseModel):
    patente: str = Field(..., min_length=3, max_length=12)
    origen: str | None = Field(default="MOBILE", max_length=20)


@router.post("/ingresos", tags=["mvp"])
def registrar_ingreso(payload: IngresoRequest, user=Depends(require_role("operador", "admin"))):
    patente = payload.patente.strip().upper()

    # Validación de duplicado
    active = find_active_ingreso_by_plate(patente)
    if active:
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

    now = datetime.now()  # hora servidor local
    id_vehiculo = get_or_create_vehicle_by_plate(patente)
    id_ingreso = create_ingreso(id_vehiculo=id_vehiculo, fecha_hora_ingreso=now, usuario=user.get("sub"))

    # Crear print job PC (obligatorio)
    hora_ingreso_iso = now.isoformat(timespec="seconds")
    server_time_iso = now.isoformat(timespec="seconds")
    ticket_payload = build_ticket_ingreso_payload(
        id_ingreso=id_ingreso,
        patente=patente,
        hora_ingreso_iso=hora_ingreso_iso,
        usuario_claims=user,
        server_time_iso=server_time_iso,
    )

    idempotency_key = f"TICKET_INGRESO:INGRESO_ID:{id_ingreso}"
    try:
        pc_job_id = create_print_job_pc_pdf(
            tipo="TICKET_INGRESO",
            id_ingreso=id_ingreso,
            patente=patente,
            payload=ticket_payload,
            idempotency_key=idempotency_key,
        )
    except Exception:
        # Para MVP: si no se crea job PC, consideramos fallo crítico
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "PRINT_JOB_CREATE_FAILED", "message": "No se pudo crear el trabajo de impresión PC"}},
        )

    return {
        "ingreso": {
            "id_ingreso": id_ingreso,
            "patente": patente,
            "hora_ingreso": hora_ingreso_iso,
            "estado": "ACTIVO",
        },
        "print": {
            "pc_job_created": True,
            "pc_job_id": pc_job_id,
            "sunmi_payload": {"enabled": False, "text": None},
        },
    }
