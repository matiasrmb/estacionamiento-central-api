from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy import text
from app.db.database import db_conn
from app.repositories.print_jobs_repo import create_print_job_pc_pdf_with_connection


class ActiveIngresoAlreadyExists(Exception):
    def __init__(self, active_ingreso: Dict[str, Any]):
        super().__init__("Active ingreso already exists for plate")
        self.active_ingreso = active_ingreso


class RequiredPrintJobCreationFailed(Exception):
    pass


class NochesNotAvailable(Exception):
    pass


class IngresoWaitingError(RuntimeError):
    pass


def find_active_ingreso_by_plate(patente: str) -> Optional[Dict[str, Any]]:
    """
    Activo = fecha_hora_salida IS NULL.
    """
    patente = patente.strip().upper()
    query = """
      SELECT i.id_ingreso, i.id_vehiculo, i.fecha_hora_ingreso, i.fecha_hora_salida,
             i.tarifa_aplicada, i.en_espera, i.cerrado, i.reingresado, i.usuario,
             v.patente
      FROM ingresos i
      JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
       WHERE v.patente = :p
         AND i.fecha_hora_salida IS NULL
         AND NOT EXISTS (
             SELECT 1 FROM ingresos_eliminados ie
             WHERE ie.id_ingreso_original = i.id_ingreso
         )
      ORDER BY i.id_ingreso DESC
      LIMIT 1
    """
    with db_conn() as conn:
        row = conn.execute(text(query), {"p": patente}).mappings().first()
        return dict(row) if row else None


def create_ingreso(id_vehiculo: int, fecha_hora_ingreso, usuario: str) -> int:
    query = """
      INSERT INTO ingresos (id_vehiculo, fecha_hora_ingreso, usuario)
      VALUES (:idv, :fhi, :usr)
    """
    with db_conn() as conn:
        conn.execute(text(query), {"idv": id_vehiculo, "fhi": fecha_hora_ingreso, "usr": usuario})
        conn.commit()
        new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return int(new_id)


def create_ingreso_for_plate_if_no_active(patente: str, fecha_hora_ingreso, usuario: str) -> Dict[str, int]:
    return _create_ingreso_for_plate_if_no_active(patente, fecha_hora_ingreso, usuario)


def create_ingreso_with_required_pc_pdf_job(
    patente: str,
    fecha_hora_ingreso,
    usuario: str,
    build_ticket_payload: Callable[[int], dict],
) -> Dict[str, int]:
    patente = patente.strip().upper()

    def create_required_job(conn, id_ingreso: int) -> int:
        try:
            ticket_payload = build_ticket_payload(id_ingreso)
            return create_print_job_pc_pdf_with_connection(
                conn,
                tipo="TICKET_INGRESO",
                id_ingreso=id_ingreso,
                patente=patente,
                payload=ticket_payload,
                idempotency_key=f"TICKET_INGRESO:INGRESO_ID:{id_ingreso}",
            )
        except Exception as exc:
            raise RequiredPrintJobCreationFailed() from exc

    return _create_ingreso_for_plate_if_no_active(patente, fecha_hora_ingreso, usuario, create_required_job)


def create_ingreso_with_noches_prepaid_and_required_pc_pdf_job(
    patente: str,
    fecha_hora_ingreso,
    usuario: str,
    build_ticket_payload: Callable[[int, Dict[str, Any]], dict],
) -> Dict[str, Any]:
    patente = patente.strip().upper()

    def create_night_charge_and_required_job(conn, id_ingreso: int) -> Dict[str, int | str]:
        cobro_noche = _create_noches_charge(conn, id_ingreso, fecha_hora_ingreso, usuario)
        try:
            pc_job_id = create_print_job_pc_pdf_with_connection(
                conn,
                tipo="TICKET_INGRESO",
                id_ingreso=id_ingreso,
                patente=patente,
                payload=build_ticket_payload(id_ingreso, cobro_noche),
                idempotency_key=f"TICKET_INGRESO:INGRESO_ID:{id_ingreso}",
            )
        except Exception as exc:
            raise RequiredPrintJobCreationFailed() from exc
        return {"cobro_noche": cobro_noche, "pc_job_id": pc_job_id}

    return _create_ingreso_for_plate_if_no_active(
        patente, fecha_hora_ingreso, usuario, create_night_charge_and_required_job
    )


def _create_noches_charge(conn, id_ingreso: int, fecha_hora_pago, usuario: str) -> Dict[str, Any]:
    rows = conn.execute(text("""
        SELECT clave, valor
        FROM configuracion
        WHERE clave IN ('noches_activo', 'noches_valor')
    """)).mappings().all()
    config = {str(row["clave"]): str(row["valor"]) for row in rows}
    try:
        monto = int(config.get("noches_valor", "0"))
    except (TypeError, ValueError) as exc:
        raise NochesNotAvailable() from exc
    if (
        config.get("noches_activo") != "1"
        or monto <= 0
    ):
        raise NochesNotAvailable()

    cobro_noche = {
        "monto_snapshot": monto,
        "hora_inicio_snapshot": "19:30",
        "hora_fin_snapshot": "09:30",
        "fecha_hora_pago": fecha_hora_pago.isoformat(timespec="seconds"),
    }
    conn.execute(text("""
        INSERT INTO cobros_noches (
            id_ingreso, monto_snapshot, hora_inicio_snapshot,
            hora_fin_snapshot, fecha_hora_pago, usuario
        ) VALUES (:id_ingreso, :monto, :hora_inicio, :hora_fin, :fecha_pago, :usuario)
    """), {
        "id_ingreso": id_ingreso,
        "monto": monto,
        "hora_inicio": cobro_noche["hora_inicio_snapshot"],
        "hora_fin": cobro_noche["hora_fin_snapshot"],
        "fecha_pago": fecha_hora_pago,
        "usuario": usuario,
    })
    return cobro_noche


def _create_ingreso_for_plate_if_no_active(
    patente: str,
    fecha_hora_ingreso,
    usuario: str,
    after_ingreso: Callable[[Any, int], Dict[str, Any] | int] | None = None,
) -> Dict[str, Any]:
    patente = patente.strip().upper()
    lock_name = f"ingreso:active:{patente}"
    locked = False
    operation_error = None

    with db_conn() as conn:
        lock_acquired = conn.execute(text("SELECT GET_LOCK(:lock_name, 5)"), {"lock_name": lock_name}).scalar()
        if lock_acquired != 1:
            raise RuntimeError("INGRESO_CREATE_LOCK_TIMEOUT")

        locked = True
        try:
            active_row = conn.execute(
                text(
                    """
                      SELECT i.id_ingreso, i.id_vehiculo, i.fecha_hora_ingreso, i.fecha_hora_salida,
                             i.tarifa_aplicada, i.en_espera, i.cerrado, i.reingresado, i.usuario,
                             v.patente
                      FROM ingresos i
                      JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
                       WHERE v.patente = :p
                         AND i.fecha_hora_salida IS NULL
                         AND NOT EXISTS (
                             SELECT 1 FROM ingresos_eliminados ie
                             WHERE ie.id_ingreso_original = i.id_ingreso
                         )
                      ORDER BY i.id_ingreso DESC
                      LIMIT 1
                    """
                ),
                {"p": patente},
            ).mappings().first()
            if active_row:
                raise ActiveIngresoAlreadyExists(dict(active_row))

            vehicle_row = conn.execute(
                text("SELECT id_vehiculo FROM vehiculos WHERE patente = :p LIMIT 1"),
                {"p": patente},
            ).mappings().first()
            if vehicle_row:
                id_vehiculo = int(vehicle_row["id_vehiculo"])
            else:
                conn.execute(
                    text("INSERT INTO vehiculos (patente, tipo_cliente, activo) VALUES (:p, 'ocasional', 1)"),
                    {"p": patente},
                )
                id_vehiculo = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())

            conn.execute(
                text(
                    """
                      INSERT INTO ingresos (id_vehiculo, fecha_hora_ingreso, usuario)
                      VALUES (:idv, :fhi, :usr)
                    """
                ),
                {"idv": id_vehiculo, "fhi": fecha_hora_ingreso, "usr": usuario},
            )
            id_ingreso = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())
            result = {"id_vehiculo": id_vehiculo, "id_ingreso": id_ingreso}
            if after_ingreso:
                after_result = after_ingreso(conn, id_ingreso)
                if isinstance(after_result, dict):
                    result.update(after_result)
                else:
                    result["pc_job_id"] = after_result
            conn.commit()
            return result
        except Exception as exc:
            operation_error = exc
            conn.rollback()
            raise
        finally:
            if locked:
                try:
                    conn.execute(text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": lock_name})
                except Exception:
                    if operation_error is None:
                        raise


def list_activos(limit: int, offset: int, search: str | None) -> Dict[str, Any]:
    """
    Lista activos por fecha_hora_salida IS NULL y en_espera=0.
    """
    where_search = ""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if search:
        where_search = " AND v.patente LIKE :s "
        params["s"] = f"%{search.strip().upper()}%"

    base = f"""
      FROM ingresos i
      JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
      WHERE i.fecha_hora_salida IS NULL
        AND i.en_espera = 0
      {where_search}
    """

    query_items = f"""
      SELECT i.id_ingreso, v.patente, i.fecha_hora_ingreso
      {base}
      ORDER BY i.fecha_hora_ingreso DESC
      LIMIT :limit OFFSET :offset
    """

    query_total = f"SELECT COUNT(*) {base}"

    with db_conn() as conn:
        items = conn.execute(text(query_items), params).mappings().all()
        total = conn.execute(text(query_total), params).scalar()

    return {"items": [dict(x) for x in items], "total": int(total)}


def get_ingreso_by_id(id_ingreso: int) -> Optional[Dict[str, Any]]:
    query = """
      SELECT i.id_ingreso, i.id_vehiculo, i.fecha_hora_ingreso, i.fecha_hora_salida,
             i.tarifa_aplicada, i.en_espera, i.cerrado, i.reingresado, i.usuario,
             v.patente
      FROM ingresos i
      JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
      WHERE i.id_ingreso = :id
      LIMIT 1
    """
    with db_conn() as conn:
        row = conn.execute(text(query), {"id": id_ingreso}).mappings().first()
        return dict(row) if row else None


def confirm_salida(id_ingreso: int, fecha_hora_salida, tarifa_aplicada: float) -> None:
    query = """
      UPDATE ingresos
      SET fecha_hora_salida = :fhs,
          tarifa_aplicada = :tar
      WHERE id_ingreso = :id
        AND fecha_hora_salida IS NULL
    """
    with db_conn() as conn:
        res = conn.execute(text(query), {"fhs": fecha_hora_salida, "tar": tarifa_aplicada, "id": id_ingreso})
        conn.commit()
        if res.rowcount != 1:
            # No actualizó: ya tenía salida o no existía
            raise RuntimeError("INGRESO_NOT_ACTIVE")


def marcar_ingreso_en_espera(id_ingreso: int) -> None:
    """Atomically hides one open, non-deleted normal ingreso from active flows."""
    with db_conn() as conn:
        updated = conn.execute(
            text("""
                UPDATE ingresos i
                SET i.en_espera = TRUE
                WHERE i.id_ingreso = :id_ingreso
                  AND i.fecha_hora_salida IS NULL
                  AND i.en_espera = FALSE
                  AND NOT EXISTS (
                      SELECT 1 FROM ingresos_eliminados ie
                      WHERE ie.id_ingreso_original = i.id_ingreso
                  )
            """),
            {"id_ingreso": id_ingreso},
        )
        if updated.rowcount == 1:
            conn.commit()
            return

        row = conn.execute(
            text("""
                SELECT i.fecha_hora_salida, i.en_espera,
                       EXISTS (
                           SELECT 1 FROM ingresos_eliminados ie
                           WHERE ie.id_ingreso_original = i.id_ingreso
                       ) AS eliminado
                FROM ingresos i
                WHERE i.id_ingreso = :id_ingreso
            """),
            {"id_ingreso": id_ingreso},
        ).mappings().first()
        conn.rollback()
    if row is None:
        raise IngresoWaitingError("INGRESO_NOT_FOUND")
    if bool(row["eliminado"]):
        raise IngresoWaitingError("INGRESO_DELETED")
    if row["fecha_hora_salida"] is not None:
        raise IngresoWaitingError("INGRESO_CLOSED")
    if bool(row["en_espera"]):
        raise IngresoWaitingError("INGRESO_ALREADY_WAITING")
    raise IngresoWaitingError("INGRESO_NOT_ACTIVE")
