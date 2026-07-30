import calendar
from datetime import date, datetime
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.database import db_conn


def current_period(today: date | None = None) -> date:
    today = today or date.today()
    return today.replace(day=1)


def effective_due_date(period: date, due_day: int) -> date:
    return period.replace(day=min(due_day, calendar.monthrange(period.year, period.month)[1]))


def payment_status(payment_exists: bool, period: date, due_day: int, today: date | None = None) -> str:
    if payment_exists:
        return "pagado"
    return "pendiente" if (today or date.today()) <= effective_due_date(period, due_day) else "vencido"


def list_mensuales(today: date | None = None) -> List[Dict[str, Any]]:
    today = today or date.today()
    period = current_period(today)
    with db_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT v.id_vehiculo, v.patente, v.tarifa_mensual, v.dia_vencimiento,
                       p.id_pago_mensual, p.fecha_pago, p.monto_snapshot
                FROM vehiculos v
                LEFT JOIN pagos_mensuales p
                  ON p.id_vehiculo = v.id_vehiculo AND p.periodo = :periodo
                WHERE v.tipo_cliente = 'mensual'
                  AND v.activo = 1
                ORDER BY v.patente ASC
            """),
            {"periodo": period},
        ).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        item["tarifa_mensual"] = int(item.get("tarifa_mensual") or 0)
        item["dia_vencimiento"] = int(item.get("dia_vencimiento") or 1)
        item["periodo_actual"] = period.isoformat()
        item["estado_pago"] = payment_status(bool(item.get("id_pago_mensual")), period, item["dia_vencimiento"], today)
        item["pagado_periodo_actual"] = bool(item.get("id_pago_mensual"))
        if item.get("fecha_pago") is not None:
            item["fecha_pago"] = item["fecha_pago"].isoformat()
        items.append(item)
    return items


def upsert_mensual(patente: str, tarifa_mensual: int | None = None) -> int:
    patente = patente.strip().upper()
    if not patente:
        raise ValueError("INVALID_PLATE")

    with db_conn() as conn:
        row = conn.execute(
            text("SELECT id_vehiculo FROM vehiculos WHERE patente = :patente LIMIT 1"),
            {"patente": patente},
        ).mappings().first()

        if row:
            id_vehiculo = int(row["id_vehiculo"])
            conn.execute(
                text("""
                    UPDATE vehiculos
                    SET tipo_cliente = 'mensual',
                        activo = 1,
                        tarifa_mensual = COALESCE(:tarifa_mensual, tarifa_mensual)
                    WHERE id_vehiculo = :id_vehiculo
                """),
                {"id_vehiculo": id_vehiculo, "tarifa_mensual": tarifa_mensual},
            )
        else:
            conn.execute(
                text("""
                    INSERT INTO vehiculos (patente, tipo_cliente, activo, tarifa_mensual)
                    VALUES (:patente, 'mensual', 1, :tarifa_mensual)
                """),
                {"patente": patente, "tarifa_mensual": tarifa_mensual},
            )
            id_vehiculo = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())

        conn.commit()
        return id_vehiculo


def update_mensual_config(id_vehiculo: int, tarifa_mensual: int, dia_vencimiento: int) -> None:
    with db_conn() as conn:
        result = conn.execute(
            text("""
                UPDATE vehiculos
                SET tarifa_mensual = :tarifa_mensual,
                    dia_vencimiento = :dia_vencimiento
                WHERE id_vehiculo = :id_vehiculo
                  AND tipo_cliente = 'mensual'
                  AND activo = 1
            """),
            {
                "id_vehiculo": id_vehiculo,
                "tarifa_mensual": tarifa_mensual,
                "dia_vencimiento": dia_vencimiento,
            },
        )
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("MENSUAL_NOT_FOUND")


def update_tarifa_mensual(id_vehiculo: int, tarifa_mensual: int) -> None:
    with db_conn() as conn:
        row = conn.execute(
            text("""
                SELECT dia_vencimiento
                FROM vehiculos
                WHERE id_vehiculo = :id_vehiculo
                  AND tipo_cliente = 'mensual'
                  AND activo = 1
            """),
            {"id_vehiculo": id_vehiculo},
        ).mappings().first()
    if not row:
        raise LookupError("MENSUAL_NOT_FOUND")
    update_mensual_config(id_vehiculo, tarifa_mensual, int(row["dia_vencimiento"] or 1))


def register_monthly_payment(
    id_vehiculo: int,
    usuario: str,
    metodo_pago: str | None = None,
    observacion: str | None = None,
    now: datetime | None = None,
) -> Dict[str, Any]:
    now = now or datetime.now()
    period = current_period(now.date())
    with db_conn() as conn:
        try:
            vehicle = conn.execute(
                text("""
                    SELECT tarifa_mensual, dia_vencimiento
                    FROM vehiculos
                    WHERE id_vehiculo = :id_vehiculo
                      AND tipo_cliente = 'mensual'
                      AND activo = 1
                    FOR UPDATE
                """),
                {"id_vehiculo": id_vehiculo},
            ).mappings().first()
            if not vehicle:
                raise LookupError("MENSUAL_NOT_FOUND")
            amount = int(vehicle["tarifa_mensual"] or 0)
            if amount <= 0:
                raise ValueError("INVALID_MONTHLY_FEE")
            existing = conn.execute(
                text("""
                    SELECT id_pago_mensual FROM pagos_mensuales
                    WHERE id_vehiculo = :id_vehiculo AND periodo = :periodo
                    FOR UPDATE
                """),
                {"id_vehiculo": id_vehiculo, "periodo": period},
            ).mappings().first()
            if existing:
                raise ValueError("MONTHLY_PAYMENT_ALREADY_EXISTS")
            due_day = int(vehicle["dia_vencimiento"] or 1)
            conn.execute(
                text("""
                    INSERT INTO pagos_mensuales (
                        id_vehiculo, periodo, dia_vencimiento_snapshot, monto_snapshot,
                        fecha_pago, usuario, metodo_pago, observacion
                    ) VALUES (
                        :id_vehiculo, :periodo, :dia_vencimiento_snapshot, :monto_snapshot,
                        :fecha_pago, :usuario, :metodo_pago, :observacion
                    )
                """),
                {
                    "id_vehiculo": id_vehiculo,
                    "periodo": period,
                    "dia_vencimiento_snapshot": due_day,
                    "monto_snapshot": amount,
                    "fecha_pago": now,
                    "usuario": usuario,
                    "metodo_pago": metodo_pago,
                    "observacion": observacion,
                },
            )
            id_pago_mensual = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())
            conn.commit()
        except IntegrityError as exc:
            conn.rollback()
            raise ValueError("MONTHLY_PAYMENT_ALREADY_EXISTS") from exc
        except Exception:
            conn.rollback()
            raise
    return {
        "id_pago_mensual": id_pago_mensual,
        "id_vehiculo": id_vehiculo,
        "periodo": period.isoformat(),
        "dia_vencimiento_snapshot": due_day,
        "monto_snapshot": amount,
        "fecha_pago": now.isoformat(),
        "usuario": usuario,
        "metodo_pago": metodo_pago,
        "observacion": observacion,
    }


def deactivate_mensual(id_vehiculo: int) -> None:
    with db_conn() as conn:
        result = conn.execute(
            text("""
                UPDATE vehiculos
                SET activo = 0
                WHERE id_vehiculo = :id_vehiculo
                  AND tipo_cliente = 'mensual'
            """),
            {"id_vehiculo": id_vehiculo},
        )
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("MENSUAL_NOT_FOUND")
