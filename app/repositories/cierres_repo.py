from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn
from app.db.schema_ensure import ensure_monthly_payments_schema
from app.repositories.accounting_contracts import build_accounting_summary


def build_cierre_summary_from_rows(
    parking_movements,
    bathroom_uses,
    wash_only_operations,
    fecha_cierre: datetime,
    expenses=None,
    monthly_payments=None,
) -> Dict[str, Any]:
    expenses = expenses or []
    monthly_payments = monthly_payments or []
    summary = build_accounting_summary(
        parking_movements, bathroom_uses, wash_only_operations, expenses, monthly_payments
    )
    dates = [row["fecha_hora_ingreso"] for row in parking_movements if row.get("fecha_hora_ingreso")]
    dates.extend(row["fecha_hora"] for row in bathroom_uses if row.get("fecha_hora"))
    dates.extend(row["fecha_hora_fin"] for row in wash_only_operations if row.get("fecha_hora_fin"))
    dates.extend(row["fecha_hora"] for row in expenses if row.get("fecha_hora"))
    dates.extend(row["fecha_pago"] for row in monthly_payments if row.get("fecha_pago"))
    fecha_inicio = min(dates) if dates else None

    return {
        "hay_pendiente": bool(parking_movements or bathroom_uses or wash_only_operations or expenses or monthly_payments),
        "fecha_inicio": fecha_inicio,
        "fecha_cierre": fecha_cierre,
        **summary,
        "ids_ingresos": [int(row["id_ingreso"]) for row in parking_movements if row.get("id_ingreso")],
        "ids_operaciones_servicio": [
            int(row["id_operacion_servicio"])
            for row in wash_only_operations
            if row.get("id_operacion_servicio")
        ],
        "ids_banos": [int(row["id_uso_bano"]) for row in bathroom_uses if row.get("id_uso_bano")],
        "ids_gastos": [int(row["id_gasto"]) for row in expenses if row.get("id_gasto")],
        "ids_pagos_mensuales": [
            int(row["id_pago_mensual"]) for row in monthly_payments if row.get("id_pago_mensual")
        ],
    }


def _build_pending_summary(conn, lock_expenses: bool = False) -> Dict[str, Any]:
    registros = conn.execute(
        text("""
            SELECT id_ingreso, fecha_hora_ingreso, fecha_hora_salida, tarifa_aplicada
            FROM ingresos
            WHERE fecha_hora_salida IS NOT NULL
              AND cerrado = FALSE
            ORDER BY fecha_hora_salida ASC
        """)
    ).mappings().all()

    fecha_cierre = datetime.now()
    lavados_solos = conn.execute(
        text("""
            SELECT id_operacion_servicio, fecha_hora_fin, estado, valor_lavado_snapshot
            FROM operaciones_servicio
            WHERE estado = 'FINALIZADO_COBRADO'
              AND COALESCE(cerrado, FALSE) = FALSE
              AND fecha_hora_fin IS NOT NULL
            ORDER BY fecha_hora_fin ASC
        """)
    ).mappings().all()

    gastos_sql = """
        SELECT id_gasto, fecha_hora, monto
        FROM gastos_operacion
        WHERE id_cierre IS NULL
        ORDER BY fecha_hora ASC, id_gasto ASC
    """
    if lock_expenses:
        gastos_sql += " FOR UPDATE"
    gastos = conn.execute(text(gastos_sql)).mappings().all()

    banos = conn.execute(
        text("""
            SELECT id AS id_uso_bano, fecha_hora, monto
            FROM usos_bano
            WHERE id_cierre IS NULL
            ORDER BY fecha_hora ASC, id ASC
        """ + (" FOR UPDATE" if lock_expenses else "")),
    ).mappings().all()

    monthly_payments_sql = """
        SELECT id_pago_mensual, fecha_pago, monto_snapshot
        FROM pagos_mensuales
        WHERE id_cierre IS NULL
        ORDER BY fecha_pago ASC, id_pago_mensual ASC
    """
    if lock_expenses:
        monthly_payments_sql += " FOR UPDATE"
    monthly_payments = conn.execute(text(monthly_payments_sql)).mappings().all()

    if not registros and not lavados_solos and not gastos and not banos and not monthly_payments:
        return {
            "hay_pendiente": False,
            "fecha_inicio": None,
            "fecha_cierre": None,
            "total_recaudado": 0,
            "total_ingresos": 0,
            "total_salidas": 0,
            "total_banos": 0,
            "total_banos_monto": 0,
            "total_lavados_solos": 0,
            "total_lavados_solos_monto": 0,
            "total_mensualidades": 0,
            "total_mensualidades_monto": 0,
            "total_general": 0,
            "total_gastos": 0,
            "total_neto": 0,
            "ids_ingresos": [],
            "ids_operaciones_servicio": [],
            "ids_banos": [],
            "ids_gastos": [],
            "ids_pagos_mensuales": [],
        }

    fechas_inicio = [row["fecha_hora_ingreso"] for row in registros]
    fechas_inicio.extend(row["fecha_hora_fin"] for row in lavados_solos)
    fechas_inicio.extend(row["fecha_hora"] for row in gastos)
    fechas_inicio.extend(row["fecha_hora"] for row in banos)
    fechas_inicio.extend(row["fecha_pago"] for row in monthly_payments)
    fecha_inicio = min(fechas_inicio)

    summary = build_cierre_summary_from_rows(
        registros, banos, lavados_solos, fecha_cierre, gastos, monthly_payments
    )
    summary["fecha_inicio"] = fecha_inicio

    return summary


def get_cierre_pendiente() -> Dict[str, Any]:
    ensure_monthly_payments_schema()
    with db_conn() as conn:
        summary = _build_pending_summary(conn)
    return _serialize_summary(summary)


def realizar_cierre(usuario: str) -> Dict[str, Any]:
    ensure_monthly_payments_schema()
    with db_conn() as conn:
        try:
            summary = _build_pending_summary(conn, lock_expenses=True)
            if not summary["hay_pendiente"]:
                raise LookupError("NO_PENDING_CLOSURE")

            conn.execute(
                text("""
                    INSERT INTO cierres_diarios (
                        fecha_inicio, fecha_cierre, total_recaudado,
                        total_ingresos, total_salidas, total_banos,
                        total_banos_monto, total_lavados_solos,
                        total_lavados_solos_monto, total_mensualidades,
                        total_mensualidades_monto, total_general, total_gastos,
                        total_neto, usuario
                    )
                    VALUES (
                        :fecha_inicio, :fecha_cierre, :total_recaudado,
                        :total_ingresos, :total_salidas, :total_banos,
                        :total_banos_monto, :total_lavados_solos,
                        :total_lavados_solos_monto, :total_mensualidades,
                        :total_mensualidades_monto, :total_general, :total_gastos,
                        :total_neto, :usuario
                    )
                """),
                {
                    **summary,
                    "usuario": usuario,
                },
            )
            id_cierre = int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())

            conn.execute(
                text("""
                    UPDATE ingresos
                    SET cerrado = TRUE
                    WHERE fecha_hora_salida IS NOT NULL
                      AND cerrado = FALSE
                      AND fecha_hora_salida <= :fecha_cierre
                """),
                {"fecha_cierre": summary["fecha_cierre"]},
            )
            conn.execute(
                text("""
                    UPDATE operaciones_servicio
                    SET cerrado = TRUE
                    WHERE estado = 'FINALIZADO_COBRADO'
                      AND COALESCE(cerrado, FALSE) = FALSE
                      AND fecha_hora_fin <= :fecha_cierre
                """),
                {"fecha_cierre": summary["fecha_cierre"]},
            )
            _link_expenses_to_cierre(conn, summary["ids_gastos"], id_cierre)
            _link_bathroom_uses_to_cierre(conn, summary.get("ids_banos", []), id_cierre)
            _link_monthly_payments_to_cierre(conn, summary.get("ids_pagos_mensuales", []), id_cierre)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    serialized = _serialize_summary(summary)
    serialized["usuario"] = usuario
    return serialized


def list_cierres(limit: int = 20) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT id_cierre, fecha_inicio, fecha_cierre, total_recaudado,
                       total_ingresos, total_salidas, total_banos,
                       total_banos_monto, total_lavados_solos,
                       total_lavados_solos_monto, total_mensualidades,
                       total_mensualidades_monto, total_general, total_gastos,
                       total_neto, usuario
                FROM cierres_diarios
                ORDER BY fecha_cierre DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()

    items = []
    for row in rows:
        item = dict(row)
        item["fecha_inicio"] = _iso(item.get("fecha_inicio"))
        item["fecha_cierre"] = _iso(item.get("fecha_cierre"))
        item["total_recaudado"] = int(item.get("total_recaudado") or 0)
        item["total_banos_monto"] = int(item.get("total_banos_monto") or 0)
        item["total_lavados_solos"] = int(item.get("total_lavados_solos") or 0)
        item["total_lavados_solos_monto"] = int(item.get("total_lavados_solos_monto") or 0)
        item["total_mensualidades"] = int(item.get("total_mensualidades") or 0)
        item["total_mensualidades_monto"] = int(item.get("total_mensualidades_monto") or 0)
        item["total_general"] = int(item.get("total_general") or 0)
        item["total_gastos"] = int(item.get("total_gastos") or 0)
        item["total_neto"] = int(item.get("total_neto") or 0)
        items.append(item)
    return items


def _serialize_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(summary)
    data.pop("ids_ingresos", None)
    data.pop("ids_banos", None)
    data.pop("ids_gastos", None)
    data.pop("ids_pagos_mensuales", None)
    data["fecha_inicio"] = _iso(data.get("fecha_inicio"))
    data["fecha_cierre"] = _iso(data.get("fecha_cierre"))
    return data


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _link_expenses_to_cierre(conn, expense_ids: List[int], id_cierre: int) -> None:
    if not expense_ids:
        return
    params = {"id_cierre": id_cierre}
    placeholders = []
    for index, expense_id in enumerate(expense_ids):
        key = f"expense_id_{index}"
        placeholders.append(f":{key}")
        params[key] = expense_id
    conn.execute(
        text(f"""
            UPDATE gastos_operacion
            SET id_cierre = :id_cierre
            WHERE id_cierre IS NULL
              AND id_gasto IN ({', '.join(placeholders)})
        """),
        params,
    )


def _link_bathroom_uses_to_cierre(conn, bathroom_use_ids: List[int], id_cierre: int) -> None:
    if not bathroom_use_ids:
        return
    params = {"id_cierre": id_cierre}
    placeholders = []
    for index, bathroom_use_id in enumerate(bathroom_use_ids):
        key = f"bathroom_use_id_{index}"
        placeholders.append(f":{key}")
        params[key] = bathroom_use_id
    conn.execute(
        text(f"""
            UPDATE usos_bano
            SET id_cierre = :id_cierre
            WHERE id_cierre IS NULL
              AND id IN ({', '.join(placeholders)})
        """),
        params,
    )


def _link_monthly_payments_to_cierre(conn, payment_ids: List[int], id_cierre: int) -> None:
    if not payment_ids:
        return
    params = {"id_cierre": id_cierre}
    placeholders = []
    for index, payment_id in enumerate(payment_ids):
        key = f"payment_id_{index}"
        placeholders.append(f":{key}")
        params[key] = payment_id
    conn.execute(
        text(f"""
            UPDATE pagos_mensuales
            SET id_cierre = :id_cierre
            WHERE id_cierre IS NULL
              AND id_pago_mensual IN ({', '.join(placeholders)})
        """),
        params,
    )
