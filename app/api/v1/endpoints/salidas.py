from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.api.deps import get_current_user
from app.db.database import db_conn
from app.schemas.salidas import SalidaPreviewIn, SalidaPreviewOut, SalidaConfirmIn, SalidaConfirmOut
from app.services.tarifas import calcular_monto_mvp
from app.services.print_jobs import crear_print_job

router = APIRouter(prefix="/salidas", tags=["salidas"])


def _get_ingreso(conn, id_ingreso: int):
    return conn.execute(
        text("""
            SELECT i.id_ingreso, i.id_vehiculo, i.fecha_hora_ingreso, i.fecha_hora_salida,
                   v.patente
            FROM ingresos i
            JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
            WHERE i.id_ingreso = :id
            LIMIT 1
        """),
        {"id": id_ingreso},
    ).mappings().first()


@router.post("/preview", response_model=SalidaPreviewOut)
def preview_salida(payload: SalidaPreviewIn, _user=Depends(get_current_user)):
    with db_conn() as conn:
        ingreso = _get_ingreso(conn, payload.id_ingreso)
        if not ingreso:
            raise HTTPException(status_code=404, detail="INGRESO_NOT_FOUND")

        if ingreso["fecha_hora_salida"] is not None:
            raise HTTPException(status_code=409, detail="INGRESO_YA_SALIO")

        fecha_ing = ingreso["fecha_hora_ingreso"]
        ahora = datetime.now()  # hora servidor
        minutos, monto, detalle = calcular_monto_mvp(conn, fecha_ing, ahora)

        return {
            "id_ingreso": int(ingreso["id_ingreso"]),
            "patente": str(ingreso["patente"]),
            "minutos": int(minutos),
            "monto": int(monto),
            "detalle": detalle,
        }


@router.post("/confirm", response_model=SalidaConfirmOut)
def confirmar_salida(payload: SalidaConfirmIn, _user=Depends(get_current_user)):
    with db_conn() as conn:
        ingreso = _get_ingreso(conn, payload.id_ingreso)
        if not ingreso:
            raise HTTPException(status_code=404, detail="INGRESO_NOT_FOUND")

        if ingreso["fecha_hora_salida"] is not None:
            raise HTTPException(status_code=409, detail="INGRESO_YA_SALIO")

        fecha_ing = ingreso["fecha_hora_ingreso"]
        ahora = datetime.now()
        minutos, monto, detalle = calcular_monto_mvp(conn, fecha_ing, ahora)

        # Persistir salida + tarifa final (ajusta nombres si tu tabla usa otro campo)
        conn.execute(
            text("""
                UPDATE ingresos
                SET fecha_hora_salida = :salida,
                    tarifa_aplicada = :monto
                WHERE id_ingreso = :id
            """),
            {"salida": ahora, "monto": monto, "id": payload.id_ingreso},
        )

        patente = str(ingreso["patente"])

        created = 0

        # PC siempre
        pc_payload = {
            "tipo": "TICKET_SALIDA",
            "id_ingreso": int(payload.id_ingreso),
            "patente": patente,
            "fecha_hora_ingreso": str(fecha_ing),
            "fecha_hora_salida": str(ahora),
            "minutos": int(minutos),
            "monto": int(monto),
            "detalle": detalle,
            "destino": "PC_PDF",
        }

        if crear_print_job(
            conn,
            tipo="TICKET_SALIDA",
            destino="PC_PDF",
            id_ingreso=int(payload.id_ingreso),
            patente=patente,
            payload=pc_payload,
            idempotency_key=f"TICKET_SALIDA_PC_{payload.id_ingreso}",
            prioridad=50,
        ):
            created += 1

        # Sunmi opcional (preparado)
        if payload.imprimir_sunmi:
            sunmi_payload = {**pc_payload, "destino": "SUNMI_TEXT", "formato": "TEXT"}
            if crear_print_job(
                conn,
                tipo="TICKET_SALIDA",
                destino="SUNMI_TEXT",
                id_ingreso=int(payload.id_ingreso),
                patente=patente,
                payload=sunmi_payload,
                idempotency_key=f"TICKET_SALIDA_SUNMI_{payload.id_ingreso}",
                prioridad=60,
            ):
                created += 1

        conn.commit()

        return {
            "id_ingreso": int(payload.id_ingreso),
            "patente": patente,
            "minutos": int(minutos),
            "monto": int(monto),
            "fecha_hora_salida": str(ahora),
            "print_jobs_creados": int(created),
        }
