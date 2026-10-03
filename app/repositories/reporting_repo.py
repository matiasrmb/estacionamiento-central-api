from datetime import datetime
from typing import Any, Dict

from sqlalchemy import text

from app.db.database import db_conn
from app.repositories.cierres_repo import get_cierre_pendiente
from app.repositories.reporting_read_models import (
    METRIC_CATALOG_VERSION,
    build_audit_inventory,
    build_operation_pagination_metadata,
    serialize_operation_row,
)


OPERATION_FILTER_SQL = {
    "category": "category = :category",
    "operator": "operator = :operator",
    "plate": "plate = :plate",
}
OPERATION_SORT_SQL = {
    "occurred_at": "occurred_at",
    "amount": "amount",
    "category": "category",
}


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

    operation_income = sum(int(rows[name] or 0) for name in ("parking_income", "bathroom_income", "wash_income", "night_income"))
    operation_expenses = int(rows["expenses"] or 0)
    operation_totals = {
        "operational_income_total": operation_income,
        "operational_expense_total": operation_expenses,
        "operational_net_total": operation_income + int(rows["mensualidades"] or 0) - operation_expenses,
        "mensualidad_sales_total": int(rows["mensualidades"] or 0),
        "vehicle_movement_count": int(rows["vehicle_count"] or 0),
    }
    closure_income = int(closure["total_general"] or 0) - int(closure["total_mensualidades_monto"] or 0)
    closure_metrics = {
        "operational_income_total": closure_income,
        "operational_expense_total": int(closure["total_gastos"] or 0),
        "mensualidad_sales_total": int(closure["total_mensualidades_monto"] or 0),
        "operational_net_total": int(closure["total_neto"] or 0),
    }
    discrepancy = {name: operation_totals[name] - closure_metrics[name] for name in closure_metrics}
    return {
        "report_id": f"closed:{cierre_id}",
        "period": _period(f"closure:{cierre_id}", closure["fecha_inicio"], closure["fecha_cierre"], "closed"),
        "catalog_version": METRIC_CATALOG_VERSION,
        "closure_reference": {"id": cierre_id, "metrics": closure_metrics},
        "operation_totals": operation_totals,
        "capacity": {
            "total_spaces": 50,
            "reserved_monthly_spaces": active_monthly_customers,
            "effective_transient_capacity": max(50 - active_monthly_customers, 0),
            "source_state": "resolved",
            "source": "vehiculos.tipo_cliente='mensual' AND activo=1",
        },
        "historical_completeness": {"status": "complete", "missing_ranges": [], "unavailable_inputs": []},
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
        }
    return build_audit_inventory(period_id, coverage)


def list_operation_rows(cierre_id: int, filters: Dict[str, str], sort: Dict[str, str], pagination: Dict[str, int]) -> Dict[str, Any]:
    with db_conn() as conn:
        closure = _get_closure_window(conn, cierre_id)
        params = {
            "id_cierre": cierre_id,
            "start": closure["fecha_inicio"],
            "end": closure["fecha_cierre"],
            "limit": pagination["limit"],
            "offset": pagination["offset"],
        }
        where_sql = _operation_filter_sql(filters, params)
        base_sql = _operation_rows_base_sql()

        total = int(
            conn.execute(
                text(f"SELECT COUNT(*) FROM ({base_sql}) operation_rows WHERE {where_sql}"),
                params,
            ).scalar()
            or 0
        )

        rows = conn.execute(
            text(
                f"""
                SELECT source, source_id, occurred_at, amount, category, operator, plate, description
                FROM ({base_sql}) operation_rows
                WHERE {where_sql}
                ORDER BY {_operation_order_sql(sort)}
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()

    return {
        "period_id": f"closure:{cierre_id}",
        "filters": dict(filters),
        "sort": dict(sort),
        "pagination": build_operation_pagination_metadata(total, pagination["limit"], pagination["offset"]),
        "items": [serialize_operation_row(row) for row in rows],
    }


def _summary(period_id, start, end, state, income, expenses, mensualidades, vehicle_count):
    return {
        "period": _period(period_id, start, end, state),
        "catalog_version": METRIC_CATALOG_VERSION,
        "filters": {"operator_session_id": None},
        "metrics": {
            "operational_income_total": income,
            "operational_expense_total": expenses,
            "operational_net_total": income + mensualidades - expenses,
            "mensualidad_sales_total": mensualidades,
            "vehicle_movement_count": vehicle_count,
        },
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


def _get_closure_window(conn, cierre_id: int):
    closure = conn.execute(
        text("""
            SELECT id_cierre, fecha_inicio, fecha_cierre
            FROM cierres_diarios
            WHERE id_cierre = :id_cierre
        """),
        {"id_cierre": cierre_id},
    ).mappings().first()
    if closure is None:
        raise LookupError("CLOSURE_NOT_FOUND")
    return closure


def _operation_filter_sql(filters: Dict[str, str], params: Dict[str, Any]) -> str:
    clauses = ["occurred_at >= :start", "occurred_at <= :end"]
    for key, value in filters.items():
        clauses.append(OPERATION_FILTER_SQL[key])
        params[key] = value
    return " AND ".join(clauses)


def _operation_order_sql(sort: Dict[str, str]) -> str:
    field = OPERATION_SORT_SQL[sort["field"]]
    direction = sort["direction"].upper()
    return f"{field} {direction}, operation_id ASC"


def _operation_rows_base_sql() -> str:
    return """
        SELECT
            'vehicle_movement' AS source,
            i.id_ingreso AS source_id,
            CONCAT('vehicle_movement:', i.id_ingreso) AS operation_id,
            i.fecha_hora_salida AS occurred_at,
            COALESCE(i.tarifa_aplicada, 0) AS amount,
            'vehicle_movement' AS category,
            i.usuario AS operator,
            v.patente AS plate,
            'Vehicle exit' AS description
        FROM ingresos i
        JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
        WHERE i.fecha_hora_salida IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM ingresos_eliminados ie
              WHERE ie.id_ingreso_original = i.id_ingreso
          )
        UNION ALL
        SELECT
            'operational_expense' AS source,
            g.id_gasto AS source_id,
            CONCAT('operational_expense:', g.id_gasto) AS operation_id,
            g.fecha_hora AS occurred_at,
            COALESCE(g.monto, 0) AS amount,
            'operational_expense' AS category,
            g.usuario AS operator,
            NULL AS plate,
            g.descripcion AS description
        FROM gastos_operacion g
        WHERE g.id_cierre = :id_cierre
        UNION ALL
        SELECT
            'mensualidad_sale' AS source,
            p.id_pago_mensual AS source_id,
            CONCAT('mensualidad_sale:', p.id_pago_mensual) AS operation_id,
            p.fecha_pago AS occurred_at,
            COALESCE(p.monto_snapshot, 0) AS amount,
            'mensualidad_sale' AS category,
            p.usuario AS operator,
            v.patente AS plate,
            p.observacion AS description
        FROM pagos_mensuales p
        JOIN vehiculos v ON v.id_vehiculo = p.id_vehiculo
        WHERE p.id_cierre = :id_cierre
    """


def _source_state(conn, table_name: str) -> str:
    try:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0
    except Exception:
        return "unavailable"
    return "available" if int(count) > 0 else "partial"
