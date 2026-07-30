from datetime import datetime, time, timedelta
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


def _get_noches_prepagadas(conn, id_ingreso: int):
    rows = conn.execute(text("""
        SELECT monto_snapshot, hora_inicio_snapshot, hora_fin_snapshot
        FROM cobros_noches
        WHERE id_ingreso = :id_ingreso
          AND estado = 'PAGADO'
        ORDER BY id_cobro_noche ASC
    """), {"id_ingreso": id_ingreso}).mappings().all()
    return [{
        "monto_snapshot": int(row["monto_snapshot"] or 0),
        "hora_inicio_snapshot": str(row["hora_inicio_snapshot"])[:5],
        "hora_fin_snapshot": str(row["hora_fin_snapshot"])[:5],
    } for row in rows]


def _get_noche_pendiente(conn, id_ingreso: int, lock: bool = False):
    lock_clause = " FOR UPDATE" if lock else ""
    return conn.execute(text("""
        SELECT id_cobro_noche, fecha_hora_pago
        FROM cobros_noches
        WHERE id_ingreso = :id_ingreso
          AND estado = 'PAGADO'
          AND estado_operativo = 'PENDIENTE'
        ORDER BY id_cobro_noche DESC
        LIMIT 1
    """ + lock_clause), {"id_ingreso": id_ingreso}).mappings().first()


def _inicio_normal_desde_diez(fecha_hora_pago: datetime) -> datetime:
    """Ancla el ingreso normal al fin de la noche cubierta por el pago."""
    fecha = fecha_hora_pago.date()
    if fecha_hora_pago.time() > time(10):
        fecha += timedelta(days=1)
    return datetime.combine(fecha, time(10))


def _require_no_noche_pendiente(conn, id_ingreso: int) -> None:
    if _get_noche_pendiente(conn, id_ingreso):
        raise HTTPException(status_code=409, detail="NOCHE_PENDIENTE_DE_REVISION")


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

        _require_no_noche_pendiente(conn, int(ingreso["id_ingreso"]))
        fecha_ing = ingreso["fecha_hora_ingreso"]
        ahora = datetime.now()  # hora servidor
        noches_prepagadas = _get_noches_prepagadas(conn, int(ingreso["id_ingreso"]))
        minutos, monto, detalle, _monto_estacionamiento, _total_lavados = calcular_monto_con_lavados(
            conn, int(ingreso["id_ingreso"]), fecha_ing, ahora
        )

        return {
            "id_ingreso": int(ingreso["id_ingreso"]),
            "patente": str(ingreso["patente"]),
            "minutos": int(minutos),
            "monto": int(monto),
            "a_cobrar_ahora": int(monto),
            "detalle": detalle,
            "noches_prepagadas": noches_prepagadas,
            "total_noches_prepagadas": sum(cobro["monto_snapshot"] for cobro in noches_prepagadas),
            "minutos_extra_antes_noche": 0,
            "minutos_extra_despues_noche": 0,
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

        _require_no_noche_pendiente(conn, int(ingreso["id_ingreso"]))
        fecha_ing = ingreso["fecha_hora_ingreso"]
        ahora = datetime.now().replace(microsecond=0)
        noches_prepagadas = _get_noches_prepagadas(conn, int(ingreso["id_ingreso"]))
        minutos, monto, detalle, monto_estacionamiento, total_lavados = calcular_monto_con_lavados(
            conn, int(ingreso["id_ingreso"]), fecha_ing, ahora
        )

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
        if noches_prepagadas:
            pc_payload["noches_prepagadas"] = noches_prepagadas

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
            "a_cobrar_ahora": int(monto),
            "fecha_hora_ingreso": fecha_ing.replace(microsecond=0).isoformat(sep=" "),
            "fecha_hora_salida": ahora.isoformat(sep=" "),
            "detalle": detalle,
            "monto_estacionamiento": int(monto_estacionamiento),
            "total_lavados": int(total_lavados),
            "noches_prepagadas": noches_prepagadas,
            "total_noches_prepagadas": sum(cobro["monto_snapshot"] for cobro in noches_prepagadas),
            "minutos_extra_antes_noche": 0,
            "minutos_extra_despues_noche": 0,
            "print_jobs_creados": int(created),
        }


@router.post("/{id_ingreso}/noche/finalizar")
def finalizar_noche(id_ingreso: int, user=Depends(require_role("operador", "admin"))):
    ahora = datetime.now().replace(microsecond=0)
    with db_conn() as conn:
        ingreso = _get_ingreso(conn, id_ingreso)
        if not ingreso or ingreso["fecha_hora_salida"] is not None:
            raise HTTPException(status_code=404, detail="INGRESO_ACTIVO_NOT_FOUND")
        noche = _get_noche_pendiente(conn, id_ingreso, lock=True)
        if not noche:
            raise HTTPException(status_code=409, detail="NOCHE_NO_PENDIENTE")
        conn.execute(text("""
            UPDATE cobros_noches SET estado_operativo = 'RETIRADO', fecha_hora_resolucion = :ahora
            WHERE id_cobro_noche = :id_cobro_noche AND estado_operativo = 'PENDIENTE'
        """), {"ahora": ahora, "id_cobro_noche": noche["id_cobro_noche"]})
        updated = conn.execute(text("""
            UPDATE ingresos SET fecha_hora_salida = :ahora, tarifa_aplicada = 0, usuario = :usuario
            WHERE id_ingreso = :id_ingreso AND fecha_hora_salida IS NULL
        """), {"ahora": ahora, "usuario": user.get("sub") or "", "id_ingreso": id_ingreso})
        if updated.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="INGRESO_YA_SALIO")
        conn.commit()
    return {"id_ingreso": id_ingreso, "estado": "RETIRADO", "monto_adicional": 0}


@router.post("/{id_ingreso}/noche/convertir")
def convertir_noche_a_ingreso_normal(id_ingreso: int, user=Depends(require_role("operador", "admin"))):
    ahora = datetime.now().replace(microsecond=0)
    with db_conn() as conn:
        ingreso = _get_ingreso(conn, id_ingreso)
        if not ingreso or ingreso["fecha_hora_salida"] is not None:
            raise HTTPException(status_code=404, detail="INGRESO_ACTIVO_NOT_FOUND")
        noche = _get_noche_pendiente(conn, id_ingreso, lock=True)
        if not noche:
            raise HTTPException(status_code=409, detail="NOCHE_NO_PENDIENTE")
        inicio_normal = _inicio_normal_desde_diez(noche["fecha_hora_pago"])
        conn.execute(text("""
            UPDATE cobros_noches SET estado_operativo = 'CONVERTIDO', fecha_hora_resolucion = :ahora
            WHERE id_cobro_noche = :id_cobro_noche AND estado_operativo = 'PENDIENTE'
        """), {"ahora": ahora, "id_cobro_noche": noche["id_cobro_noche"]})
        updated = conn.execute(text("""
            UPDATE ingresos SET fecha_hora_ingreso = :inicio_normal, usuario = :usuario
            WHERE id_ingreso = :id_ingreso AND fecha_hora_salida IS NULL
        """), {"inicio_normal": inicio_normal, "usuario": user.get("sub") or "", "id_ingreso": id_ingreso})
        if updated.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="INGRESO_YA_SALIO")
        conn.commit()
    return {"id_ingreso": id_ingreso, "estado": "CONVERTIDO", "fecha_hora_ingreso": inicio_normal.isoformat()}
