from datetime import datetime
from typing import Any, Dict

from sqlalchemy import text

from app.db.database import db_conn
from app.repositories.cierres_repo import get_cierre_pendiente
from app.repositories.reporting_read_models import (
    COLLECTED_SOURCES_TOTAL,
    COVERAGE_AVAILABLE,
    COVERAGE_PARTIAL,
    COVERAGE_UNAVAILABLE,
    METRIC_CATALOG_VERSION,
    MONTHLY_PAYMENTS_COLLECTED_TOTAL,
    NET_REVENUE_TOTAL,
    OPERATIONAL_EXPENSE_TOTAL,
    PLATE_HISTORY_SOURCES,
    VEHICLE_MOVEMENT_COUNT,
    build_audit_inventory,
    build_capacity,
    build_historical_capacity_completeness,
    build_plate_history_response,
    _with_legacy_metric_aliases,
)


PLATE_HISTORY_SOURCE_QUERIES = dict(zip(PLATE_HISTORY_SOURCES, (
    """
        SELECT i.id_ingreso AS id,
               v.patente AS plate,
               i.fecha_hora_salida AS occurred_at,
               i.tarifa_aplicada AS amount,
               NULL AS closure_id
        FROM ingresos i
        JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
        WHERE v.patente = :plate
          AND i.fecha_hora_salida >= :start
          AND i.fecha_hora_salida <= :end
          AND i.fecha_hora_salida IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM ingresos_eliminados ie
              WHERE ie.id_ingreso_original = i.id_ingreso
          )
        ORDER BY i.fecha_hora_salida ASC, i.id_ingreso ASC
        LIMIT :limit
    """,
    """
        SELECT o.id_operacion_servicio AS id,
               o.patente AS plate,
               o.fecha_hora_fin AS occurred_at,
               o.valor_lavado_snapshot AS amount,
               NULL AS closure_id
        FROM operaciones_servicio o
        WHERE o.patente = :plate
          AND o.fecha_hora_fin >= :start
          AND o.fecha_hora_fin <= :end
          AND o.estado = 'FINALIZADO_COBRADO'
        ORDER BY o.fecha_hora_fin ASC, o.id_operacion_servicio ASC
        LIMIT :limit
    """,
    """
        SELECT p.id_pago_mensual AS id,
               v.patente AS plate,
               p.fecha_pago AS occurred_at,
               p.periodo AS period,
               p.monto_snapshot AS amount,
               p.id_cierre AS closure_id
        FROM pagos_mensuales p
        JOIN vehiculos v ON v.id_vehiculo = p.id_vehiculo
        WHERE v.patente = :plate
          AND p.fecha_pago >= :start
          AND p.fecha_pago <= :end
        ORDER BY p.fecha_pago ASC, p.id_pago_mensual ASC
        LIMIT :limit
    """,
    """
        SELECT n.id_cobro_noche AS id,
               v.patente AS plate,
               n.fecha_hora_pago AS occurred_at,
               n.monto_snapshot AS amount,
               n.id_cierre AS closure_id
        FROM cobros_noches n
        JOIN ingresos i ON i.id_ingreso = n.id_ingreso
        JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
        WHERE v.patente = :plate
          AND n.fecha_hora_pago >= :start
          AND n.fecha_hora_pago <= :end
          AND n.estado = 'PAGADO'
        ORDER BY n.fecha_hora_pago ASC, n.id_cobro_noche ASC
        LIMIT :limit
    """,
    """
        SELECT c.id_cierre AS id,
               :plate AS plate,
               c.fecha_cierre AS occurred_at,
               c.id_cierre AS closure_id
        FROM cierres_diarios c
        WHERE c.fecha_cierre >= :start
          AND c.fecha_cierre <= :end
          AND EXISTS (
              SELECT 1
              FROM ingresos i
              JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
              WHERE v.patente = :plate
                AND i.fecha_hora_salida >= c.fecha_inicio
                AND i.fecha_hora_salida <= c.fecha_cierre
          )
        ORDER BY c.fecha_cierre ASC, c.id_cierre ASC
        LIMIT :limit
    """,
    """
        SELECT ie.id_ingreso_original AS id,
               v.patente AS plate,
               COALESCE(i.fecha_hora_salida, i.fecha_hora_ingreso) AS occurred_at,
               i.tarifa_aplicada AS amount,
               NULL AS closure_id
        FROM ingresos_eliminados ie
        JOIN ingresos i ON i.id_ingreso = ie.id_ingreso_original
        JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
        WHERE v.patente = :plate
          AND COALESCE(i.fecha_hora_salida, i.fecha_hora_ingreso) >= :start
          AND COALESCE(i.fecha_hora_salida, i.fecha_hora_ingreso) <= :end
        ORDER BY COALESCE(i.fecha_hora_salida, i.fecha_hora_ingreso) ASC,
                 ie.id_ingreso_original ASC
        LIMIT :limit
    """,
)))


def get_open_dashboard() -> Dict[str, Any]:
    pending = get_cierre_pendiente()
    now = datetime.now()
    with db_conn() as conn:
        latest = conn.execute(
            text("""
                SELECT id_cierre, fecha_cierre
                FROM cierres_diarios
                ORDER BY fecha_cierre DESC
                LIMIT 1
            """)
        ).mappings().first()

    start = latest["fecha_cierre"] if latest else pending.get("fecha_inicio") or now
    period_id = f"open:{latest['id_cierre']}" if latest else "open:initial"
    income = int(pending.get("total_general") or 0) - int(pending.get("total_mensualidades_monto") or 0)
    expenses = int(pending.get("total_gastos") or 0)
    return _summary(
        period_id=period_id,
        start=start,
        end=now,
        state="open",
        income=income,
        expenses=expenses,
        mensualidades=int(pending.get("total_mensualidades_monto") or 0),
        vehicle_count=int(pending.get("total_salidas") or 0),
    )


def get_closed_report(cierre_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        closure = conn.execute(
            text("""
                SELECT id_cierre, fecha_inicio, fecha_cierre, total_general,
                       total_mensualidades_monto, total_gastos, total_neto
                FROM cierres_diarios
                WHERE id_cierre = :id_cierre
            """),
            {"id_cierre": cierre_id},
        ).mappings().first()
        if closure is None:
            raise LookupError("CLOSURE_NOT_FOUND")

        rows = conn.execute(
            text("""
                SELECT
                    (SELECT COUNT(*) FROM ingresos i
                     WHERE i.fecha_hora_salida >= :start AND i.fecha_hora_salida <= :end
                       AND i.fecha_hora_salida IS NOT NULL
                       AND NOT EXISTS (SELECT 1 FROM ingresos_eliminados ie WHERE ie.id_ingreso_original = i.id_ingreso)) AS vehicle_count,
                    (SELECT COALESCE(SUM(i.tarifa_aplicada), 0) FROM ingresos i
                     WHERE i.fecha_hora_salida >= :start AND i.fecha_hora_salida <= :end
                       AND i.fecha_hora_salida IS NOT NULL
                       AND NOT EXISTS (SELECT 1 FROM ingresos_eliminados ie WHERE ie.id_ingreso_original = i.id_ingreso)) AS parking_income,
                    (SELECT COALESCE(SUM(b.monto), 0) FROM usos_bano b WHERE b.id_cierre = :id_cierre) AS bathroom_income,
                    (SELECT COALESCE(SUM(o.valor_lavado_snapshot), 0) FROM operaciones_servicio o
                     WHERE o.fecha_hora_fin >= :start AND o.fecha_hora_fin <= :end
                       AND o.estado = 'FINALIZADO_COBRADO' AND o.id_ingreso_generado IS NULL) AS wash_income,
                    (SELECT COALESCE(SUM(n.monto_snapshot), 0) FROM cobros_noches n
                     WHERE n.id_cierre = :id_cierre AND n.estado = 'PAGADO') AS night_income,
                    (SELECT COALESCE(SUM(g.monto), 0) FROM gastos_operacion g WHERE g.id_cierre = :id_cierre) AS expenses,
                    (SELECT COALESCE(SUM(p.monto_snapshot), 0) FROM pagos_mensuales p WHERE p.id_cierre = :id_cierre) AS mensualidades
            """),
            {"id_cierre": cierre_id, "start": closure["fecha_inicio"], "end": closure["fecha_cierre"]},
        ).mappings().one()
        active_monthly_customers = _active_monthly_customers(conn)

    collected_sources_total = sum(int(rows[name] or 0) for name in ("parking_income", "bathroom_income", "wash_income", "night_income"))
    monthly_payments_collected_total = int(rows["mensualidades"] or 0)
    operation_expenses = int(rows["expenses"] or 0)
    operation_totals = _with_legacy_metric_aliases({
        COLLECTED_SOURCES_TOTAL: collected_sources_total,
        OPERATIONAL_EXPENSE_TOTAL: operation_expenses,
        NET_REVENUE_TOTAL: collected_sources_total + monthly_payments_collected_total - operation_expenses,
        MONTHLY_PAYMENTS_COLLECTED_TOTAL: monthly_payments_collected_total,
        VEHICLE_MOVEMENT_COUNT: int(rows["vehicle_count"] or 0),
    })
    closure_income = int(closure["total_general"] or 0) - int(closure["total_mensualidades_monto"] or 0)
    closure_metrics = _with_legacy_metric_aliases({
        COLLECTED_SOURCES_TOTAL: closure_income,
        OPERATIONAL_EXPENSE_TOTAL: int(closure["total_gastos"] or 0),
        MONTHLY_PAYMENTS_COLLECTED_TOTAL: int(closure["total_mensualidades_monto"] or 0),
        NET_REVENUE_TOTAL: int(closure["total_neto"] or 0),
    })
    discrepancy = {
        name: operation_totals[name] - closure_metrics[name]
        for name in (COLLECTED_SOURCES_TOTAL, OPERATIONAL_EXPENSE_TOTAL, NET_REVENUE_TOTAL)
    }
    discrepancy = _with_legacy_metric_aliases(discrepancy)
    return {
        "report_id": f"closed:{cierre_id}",
        "period": _period(f"closure:{cierre_id}", closure["fecha_inicio"], closure["fecha_cierre"], "closed"),
        "catalog_version": METRIC_CATALOG_VERSION,
        "closure_reference": {"id": cierre_id, "metrics": closure_metrics},
        "operation_totals": operation_totals,
        "capacity": build_capacity(active_monthly_customers),
        "historical_completeness": build_historical_capacity_completeness(),
        "operation_drill_down": {
            "href": f"/api/v1/reporting/reports/operations?period_id=closure:{cierre_id}",
            "period_id": f"closure:{cierre_id}",
        },
        "discrepancy": {
            "status": "none" if all(value == 0 for value in discrepancy.values()) else "delta",
            "metrics": discrepancy,
            "compared_sources": ["closure_reference", "operational_rows"],
        },
        "source_state": "closed_snapshot_with_operational_drill_down",
    }


def get_audit_inventory(period_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        coverage = {
            "closures": _source_state(conn, "cierres_diarios"),
            "operational_rows": _source_state(conn, "ingresos"),
            "payments": _source_state(conn, "pagos_mensuales"),
            "expenses": _source_state(conn, "gastos_operacion"),
            "print_jobs": _source_state(conn, "trabajos_impresion"),
            "users": _source_state(conn, "usuarios"),
            "operator_sessions": _source_state(conn, "asistencias"),
            "parking": _source_state(conn, "ingresos"),
            "solo_wash": _source_state(conn, "operaciones_servicio"),
            "monthly_payment": _source_state(conn, "pagos_mensuales"),
            "night_charge": _source_state(conn, "cobros_noches"),
            "closure": _source_state(conn, "cierres_diarios"),
            "logical_deletion": _source_state(conn, "ingresos_eliminados"),
        }
    return build_audit_inventory(period_id, coverage)


def get_plate_history(plate: str, start: datetime, end: datetime, limit: int = 500) -> Dict[str, Any]:
    if start >= end:
        raise ValueError("INVALID_HISTORY_BOUNDS")
    if not 1 <= int(limit) <= 500:
        raise ValueError("INVALID_HISTORY_LIMIT")

    rows = []
    coverage = {}
    params = {"plate": plate, "start": start, "end": end, "limit": int(limit)}
    with db_conn() as conn:
        for source, query in PLATE_HISTORY_SOURCE_QUERIES.items():
            try:
                source_rows = [dict(row) for row in conn.execute(text(query), params).mappings().all()]
            except Exception:
                coverage[source] = COVERAGE_UNAVAILABLE
                continue
            coverage[source] = COVERAGE_AVAILABLE
            rows.extend(_plate_history_rows(source, source_rows))

    rows.sort(key=_plate_history_sort_key)
    return build_plate_history_response(
        plate,
        {"start": start, "end": end, "limit": int(limit)},
        rows=rows[: int(limit)],
        coverage=coverage,
    )


def _summary(period_id, start, end, state, income, expenses, mensualidades, vehicle_count):
    metrics = _with_legacy_metric_aliases({
        COLLECTED_SOURCES_TOTAL: income,
        OPERATIONAL_EXPENSE_TOTAL: expenses,
        NET_REVENUE_TOTAL: income + mensualidades - expenses,
        MONTHLY_PAYMENTS_COLLECTED_TOTAL: mensualidades,
        VEHICLE_MOVEMENT_COUNT: vehicle_count,
    })
    return {
        "period": _period(period_id, start, end, state),
        "catalog_version": METRIC_CATALOG_VERSION,
        "filters": {"operator_session_id": None},
        "metrics": metrics,
        "pagination": {"summary_row_count": vehicle_count, "summary_is_complete": True},
    }


def _period(period_id, start, end, state):
    return {"id": period_id, "start": _iso(start), "end": _iso(end), "state": state}


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _active_monthly_customers(conn) -> int:
    return int(
        conn.execute(
            text("""
                SELECT COUNT(DISTINCT v.id_vehiculo)
                FROM vehiculos v
                WHERE v.tipo_cliente = 'mensual'
                  AND v.activo = 1
            """)
        ).scalar()
        or 0
    )


def _plate_history_rows(source, source_rows):
    rows = []
    for row in source_rows:
        item = {
            "source": source,
            "id": row.get("id"),
            "plate": row.get("plate"),
            "occurred_at": row.get("occurred_at"),
            "period": row.get("period"),
            "amount": row.get("amount"),
            "closure_id": row.get("closure_id"),
        }
        rows.append(item)
    return rows


def _plate_history_sort_key(row):
    business_time = row.get("occurred_at") or row.get("period") or ""
    return (str(business_time), row.get("source") or "", row.get("id") or 0)


def _source_state(conn, table_name: str) -> str:
    try:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0
    except Exception:
        return COVERAGE_UNAVAILABLE
    return COVERAGE_AVAILABLE if int(count) > 0 else COVERAGE_PARTIAL
