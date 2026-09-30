from datetime import datetime
from typing import Any, Dict

from sqlalchemy import text

from app.db.database import db_conn
from app.repositories.cierres_repo import get_cierre_pendiente
from app.repositories.reporting_read_models import METRIC_CATALOG_VERSION


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

    operation_income = sum(int(rows[name] or 0) for name in ("parking_income", "bathroom_income", "wash_income", "night_income"))
    operation_expenses = int(rows["expenses"] or 0)
    operation_totals = {
        "operational_income_total": operation_income,
        "operational_expense_total": operation_expenses,
        "operational_net_total": operation_income - operation_expenses,
        "mensualidad_sales_total": int(rows["mensualidades"] or 0),
        "vehicle_movement_count": int(rows["vehicle_count"] or 0),
    }
    closure_income = int(closure["total_general"] or 0) - int(closure["total_mensualidades_monto"] or 0)
    closure_metrics = {
        "operational_income_total": closure_income,
        "operational_expense_total": int(closure["total_gastos"] or 0),
        "operational_net_total": int(closure["total_neto"] or 0),
    }
    discrepancy = {name: operation_totals[name] - closure_metrics[name] for name in closure_metrics}
    return {
        "report_id": f"closed:{cierre_id}",
        "period": _period(f"closure:{cierre_id}", closure["fecha_inicio"], closure["fecha_cierre"], "closed"),
        "catalog_version": METRIC_CATALOG_VERSION,
        "closure_reference": {"id": cierre_id, "metrics": closure_metrics},
        "operation_totals": operation_totals,
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


def _summary(period_id, start, end, state, income, expenses, mensualidades, vehicle_count):
    return {
        "period": _period(period_id, start, end, state),
        "catalog_version": METRIC_CATALOG_VERSION,
        "filters": {"operator_session_id": None},
        "metrics": {
            "operational_income_total": income,
            "operational_expense_total": expenses,
            "operational_net_total": income - expenses,
            "mensualidad_sales_total": mensualidades,
            "vehicle_movement_count": vehicle_count,
        },
        "pagination": {"summary_row_count": vehicle_count, "summary_is_complete": True},
    }


def _period(period_id, start, end, state):
    return {"id": period_id, "start": _iso(start), "end": _iso(end), "state": state}


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
