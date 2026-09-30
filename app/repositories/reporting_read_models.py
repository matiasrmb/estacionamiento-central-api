from datetime import datetime
from typing import Any, Dict, Iterable, List


METRIC_CATALOG_VERSION = "2026-09-29"

METRIC_CATALOG = [
    {
        "name": "operational_income_total",
        "meaning": "Payments collected from operational sources",
        "sign": "positive",
    },
    {
        "name": "operational_expense_total",
        "meaning": "Operational expenses",
        "sign": "positive_expense_negative_result",
    },
    {
        "name": "operational_net_total",
        "meaning": "Income minus expenses",
        "sign": "signed",
    },
    {
        "name": "mensualidad_sales_total",
        "meaning": "Commercial mensualidad activity",
        "sign": "positive",
    },
    {
        "name": "vehicle_movement_count",
        "meaning": "Vehicle entries/exits in the period",
        "sign": "count",
    },
]


def build_metric_catalog() -> Dict[str, Any]:
    return {
        "version": METRIC_CATALOG_VERSION,
        "metrics": [metric.copy() for metric in METRIC_CATALOG],
        "unsupported": [
            "taxes",
            "commissions",
            "payment_method_accounting",
            "formal_ledger_balances",
        ],
    }


def build_operational_periods(closures, now: datetime) -> List[Dict[str, Any]]:
    ordered_closures = sorted(closures, key=lambda closure: closure["closed_at"])
    periods = []

    for previous, next_closure in zip(ordered_closures, ordered_closures[1:]):
        periods.append(
            {
                "id": f"closure:{previous['id']}:{next_closure['id']}",
                "start": previous["closed_at"],
                "end": next_closure["closed_at"],
                "state": "closed",
                "start_closure_id": previous["id"],
                "end_closure_id": next_closure["id"],
            }
        )

    if ordered_closures:
        latest_closure = ordered_closures[-1]
        periods.append(
            {
                "id": f"open:{latest_closure['id']}",
                "start": latest_closure["closed_at"],
                "end": now,
                "state": "open",
                "start_closure_id": latest_closure["id"],
                "end_closure_id": None,
            }
        )

    return periods


def build_reporting_summary(
    period,
    vehicle_movements,
    expenses=None,
    mensualidades=None,
    operator_sessions=None,
    operator_session_id=None,
) -> Dict[str, Any]:
    expenses = expenses or []
    mensualidades = mensualidades or []
    operator_sessions = operator_sessions or []

    movements_in_period = _rows_in_period(vehicle_movements, period)
    expenses_in_period = _rows_in_period(expenses, period)
    mensualidades_in_period = _rows_in_period(mensualidades, period)

    selected_session = _find_operator_session(operator_sessions, operator_session_id)
    if selected_session:
        movements_in_period = _rows_in_operator_session(movements_in_period, selected_session)
        expenses_in_period = _rows_in_operator_session(expenses_in_period, selected_session)
        mensualidades_in_period = _rows_in_operator_session(mensualidades_in_period, selected_session)

    operational_income_total = _sum_amount(movements_in_period)
    operational_expense_total = _sum_amount(expenses_in_period)
    mensualidad_sales_total = _sum_amount(mensualidades_in_period)

    return {
        "period": {
            "id": period["id"],
            "start": _iso(period["start"]),
            "end": _iso(period["end"]),
            "state": period["state"],
        },
        "catalog_version": METRIC_CATALOG_VERSION,
        "filters": {"operator_session_id": operator_session_id},
        "metrics": {
            "operational_income_total": operational_income_total,
            "operational_expense_total": operational_expense_total,
            "operational_net_total": operational_income_total - operational_expense_total,
            "mensualidad_sales_total": mensualidad_sales_total,
            "vehicle_movement_count": len(movements_in_period),
        },
        "pagination": {
            "summary_row_count": len(movements_in_period),
            "summary_is_complete": True,
        },
    }


def build_closed_report(closure, vehicle_movements, expenses=None, mensualidades=None) -> Dict[str, Any]:
    expenses = expenses or []
    period = {
        "id": f"closure:{closure['id']}",
        "start": closure["period_start"],
        "end": closure["closed_at"],
        "state": "closed",
    }
    summary = build_reporting_summary(period, vehicle_movements, expenses, mensualidades)
    closure_metrics = {
        "operational_income_total": int(closure.get("operational_income_total") or 0),
        "operational_expense_total": int(closure.get("operational_expense_total") or 0),
    }
    closure_metrics["operational_net_total"] = (
        closure_metrics["operational_income_total"] - closure_metrics["operational_expense_total"]
    )
    operation_totals = summary["metrics"]
    discrepancy_metrics = {
        name: operation_totals.get(name, 0) - closure_metrics.get(name, 0)
        for name in ("operational_income_total", "operational_expense_total", "operational_net_total")
    }

    return {
        "report_id": f"closed:{closure['id']}",
        "period": summary["period"],
        "catalog_version": METRIC_CATALOG_VERSION,
        "closure_reference": {"id": closure["id"], "metrics": closure_metrics},
        "operation_totals": operation_totals,
        "operation_drill_down": _operation_drill_down(vehicle_movements, expenses or [], period),
        "discrepancy": {
            "status": "none" if all(value == 0 for value in discrepancy_metrics.values()) else "delta",
            "metrics": discrepancy_metrics,
            "compared_sources": ["closure_reference", "operational_rows"],
        },
        "source_state": "closed_snapshot_with_operational_drill_down",
    }


def build_audit_inventory(period_id: str) -> Dict[str, Any]:
    return {
        "period_id": period_id,
        "available_sources": [
            "closures",
            "operational_rows",
            "payments",
            "expenses",
            "print_jobs",
            "users",
            "operator_sessions",
        ],
        "unavailable_history": ["before_first_closure", "after_current_rows"],
        "requires_event_sourcing": False,
    }


def build_report_export(report, export_format: str, generated_at: datetime) -> Dict[str, Any]:
    normalized_format = export_format.lower()
    if normalized_format not in {"csv", "pdf"}:
        raise ValueError("UNSUPPORTED_EXPORT_FORMAT")

    metadata = {
        "report_id": report["report_id"],
        "period_start": report["period"]["start"],
        "period_end": report["period"]["end"],
        "closure_reference_id": report["closure_reference"]["id"],
        "generated_at": _iso(generated_at),
        "metric_catalog_version": report["catalog_version"],
        "filters": report.get("filters", {}),
        "source_state": report["source_state"],
        "template_version": "reporting-export-2026-09-29",
    }

    if normalized_format == "csv":
        content = _render_csv_export(metadata, report)
        content_type = "text/csv"
    else:
        content = _render_pdf_export(metadata, report)
        content_type = "application/pdf"

    return {"format": normalized_format, "content_type": content_type, "metadata": metadata, "content": content}


def _rows_in_period(rows: Iterable[Dict[str, Any]], period: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        row
        for row in rows
        if period["start"] <= row["occurred_at"] < period["end"]
    ]


def _find_operator_session(operator_sessions, operator_session_id):
    if not operator_session_id:
        return None
    for session in operator_sessions:
        if session.get("session_id") == operator_session_id:
            return session
    return None


def _rows_in_operator_session(rows, session):
    return [
        row
        for row in rows
        if session["start"] <= row["occurred_at"] < session["end"]
        and (not row.get("operator") or row.get("operator") == session.get("operator"))
    ]


def _sum_amount(rows):
    return sum(int(row.get("amount") or 0) for row in rows)


def _operation_drill_down(vehicle_movements, expenses, period):
    items = []
    for row in _rows_in_period(vehicle_movements, period):
        item = row.copy()
        item["canonical_category"] = "vehicle_movement"
        item["occurred_at"] = _iso(item.get("occurred_at"))
        items.append(item)
    for row in _rows_in_period(expenses, period):
        item = row.copy()
        item["canonical_category"] = "operational_expense"
        item["occurred_at"] = _iso(item.get("occurred_at"))
        items.append(item)
    return items


def _render_csv_export(metadata, report):
    rows = [[key, value] for key, value in metadata.items()]
    rows.extend(
        [
            ["operational_income_total", report["closure_reference"]["metrics"]["operational_income_total"]],
            ["operational_expense_total", report["closure_reference"]["metrics"]["operational_expense_total"]],
            ["operational_net_total", report["closure_reference"]["metrics"]["operational_net_total"]],
        ]
    )
    return "\n".join(f"{key},{value}" for key, value in rows)


def _render_pdf_export(metadata, report):
    metrics = report["closure_reference"]["metrics"]
    return "\n".join(
        [
            "Closed Report Export",
            f"Report ID: {metadata['report_id']}",
            f"Period Start: {metadata['period_start']}",
            f"Period End: {metadata['period_end']}",
            f"Closure Reference ID: {metadata['closure_reference_id']}",
            f"Generated At: {metadata['generated_at']}",
            f"Metric Catalog Version: {metadata['metric_catalog_version']}",
            f"Source State: {metadata['source_state']}",
            f"Template Version: {metadata['template_version']}",
            f"Operational Income Total: {metrics['operational_income_total']}",
            f"Operational Expense Total: {metrics['operational_expense_total']}",
            f"Operational Net Total: {metrics['operational_net_total']}",
        ]
    )


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
