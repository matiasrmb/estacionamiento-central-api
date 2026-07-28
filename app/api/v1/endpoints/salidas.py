from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.api.deps import require_role
from app.db.database import db_conn
from app.schemas.salidas import SalidaPreviewIn, SalidaPreviewOut, SalidaConfirmIn, SalidaConfirmOut
from app.services.tarifas import calcular_monto_con_lavados
from app.services.print_jobs import crear_print_job

router = APIRouter(prefix="/salidas", tags=["salidas"])


def _get_ingreso(conn, id_ingreso: int):
    return conn.execute(
        text("""
            SELECT i.id_ingreso, i.id_vehiculo, i.fecha_hora_ingreso, i.fecha_hora_salida,
                   i.en_lavado, v.patente
            FROM ingresos i
            JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
            WHERE i.id_ingreso = :id
            LIMIT 1
        """),
        {"id": id_ingreso},
    ).mappings().first()


@router.post("/preview", response_model=SalidaPreviewOut)
def preview_salida(payload: SalidaPreviewIn, _user=Depends(require_role("operador", "admin"))):
    with db_conn() as conn:
        ingreso = _get_ingreso(conn, payload.id_ingreso)
        if not ingreso:
            raise HTTPException(status_code=404, detail="INGRESO_NOT_FOUND")

        if ingreso["fecha_hora_salida"] is not None:
            raise HTTPException(status_code=409, detail="INGRESO_YA_SALIO")

        if int(ingreso.get("en_lavado") or 0) == 1:
            raise HTTPException(status_code=409, detail="VEHICULO_EN_LAVADO")

        fecha_ing = ingreso["fecha_hora_ingreso"]
        ahora = datetime.now()  # hora servidor
        minutos, monto, detalle, _monto_estacionamiento, _total_lavados = calcular_monto_con_lavados(conn, int(ingreso["id_ingreso"]), fecha_ing, ahora)

        return {
            "id_ingreso": int(ingreso["id_ingreso"]),
            "patente": str(ingreso["patente"]),
            "minutos": int(minutos),
            "monto": int(monto),
            "detalle": detalle,
        }


@router.post("/confirm", response_model=SalidaConfirmOut)
def confirmar_salida(payload: SalidaConfirmIn, user=Depends(require_role("operador", "admin"))):
    with db_conn() as conn:
        ingreso = _get_ingreso(conn, payload.id_ingreso)
        if not ingreso:
            raise HTTPException(status_code=404, detail="INGRESO_NOT_FOUND")

        if ingreso["fecha_hora_salida"] is not None:
            raise HTTPException(status_code=409, detail="INGRESO_YA_SALIO")

        if int(ingreso.get("en_lavado") or 0) == 1:
            raise HTTPException(status_code=409, detail="VEHICULO_EN_LAVADO")

        fecha_ing = ingreso["fecha_hora_ingreso"]
        ahora = datetime.now().replace(microsecond=0)
        minutos, monto, detalle, monto_estacionamiento, total_lavados = calcular_monto_con_lavados(conn, int(ingreso["id_ingreso"]), fecha_ing, ahora)

        # Persistir salida + tarifa final (ajusta nombres si tu tabla usa otro campo)
        update_result = conn.execute(
            text("""
                UPDATE ingresos
                SET fecha_hora_salida = :salida,
                    tarifa_aplicada = :monto,
                    usuario = :usuario
                WHERE id_ingreso = :id
                  AND fecha_hora_salida IS NULL
            """),
            {"salida": ahora, "monto": monto, "usuario": user.get("sub") or "", "id": payload.id_ingreso},
        )
        if update_result.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="INGRESO_YA_SALIO")

        patente = str(ingreso["patente"])

        created = 0

        # PC siempre
        pc_payload = {
            "kind": "TICKET_SALIDA",
            "tipo": "TICKET_SALIDA",
            "id_ingreso": int(payload.id_ingreso),
            "patente": patente,
            "hora_ingreso": fecha_ing.replace(microsecond=0).isoformat(sep=" "),
            "hora_salida": ahora.isoformat(sep=" "),
            "fecha_hora_ingreso": fecha_ing.replace(microsecond=0).isoformat(sep=" "),
            "fecha_hora_salida": ahora.isoformat(sep=" "),
            "minutos_cobrados": int(minutos),
            "minutos": int(minutos),
            "monto_final": int(monto),
            "monto": int(monto),
            "detalle": {
                "texto": detalle,
                "monto_estacionamiento": int(monto_estacionamiento),
                "total_lavados": int(total_lavados),
            },
            "detalle_texto": detalle,
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

        conn.commit()

        return {
            "id_ingreso": int(payload.id_ingreso),
            "patente": patente,
            "minutos": int(minutos),
            "monto": int(monto),
            "fecha_hora_ingreso": fecha_ing.replace(microsecond=0).isoformat(sep=" "),
            "fecha_hora_salida": ahora.isoformat(sep=" "),
            "detalle": detalle,
            "monto_estacionamiento": int(monto_estacionamiento),
            "total_lavados": int(total_lavados),
            "print_jobs_creados": int(created),
        }
