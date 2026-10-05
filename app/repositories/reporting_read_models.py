from datetime import datetime
from typing import Any, Dict, Iterable, List


METRIC_CATALOG_VERSION = "2026-09-29"
TOTAL_PARKING_SPACES = 50
COMPLETENESS_STATUSES = {"complete", "partial", "unavailable"}
COVERAGE_AVAILABLE = "available"
COVERAGE_PARTIAL = "partial"
COVERAGE_UNAVAILABLE = "unavailable"
COVERAGE_STATES = {COVERAGE_AVAILABLE, COVERAGE_PARTIAL, COVERAGE_UNAVAILABLE}
PLATE_HISTORY_SOURCES = (
    "parking",
    "solo_wash",
    "monthly_payment",
    "night_charge",
    "closure",
    "logical_deletion",
)
AUDIT_INVENTORY_UNSUPPORTED_BEHAVIORS = [
    "persisted_anomaly_records",
    "event_sourced_history",
    "transversal_audit_log",
]
CANONICAL_EXPORT_FORMATS = {"pdf", "xlsx"}
LEGACY_EXPORT_FORMATS = {"csv"}

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
            "operational_net_total": operational_income_total + mensualidad_sales_total - operational_expense_total,
            "mensualidad_sales_total": mensualidad_sales_total,
            "vehicle_movement_count": len(movements_in_period),
        },
        "pagination": {
            "summary_row_count": len(movements_in_period),
            "summary_is_complete": True,
        },
    }


def build_capacity(active_monthly_customers=None) -> Dict[str, Any]:
    if active_monthly_customers is None:
        return {
            "total_spaces": TOTAL_PARKING_SPACES,
            "reserved_monthly_spaces": None,
            "effective_transient_capacity": None,
            "source_state": "unavailable",
            "unavailable_inputs": ["active_monthly_customers"],
        }

    reserved = int(active_monthly_customers)
    return {
        "total_spaces": TOTAL_PARKING_SPACES,
        "reserved_monthly_spaces": reserved,
        "effective_transient_capacity": max(TOTAL_PARKING_SPACES - reserved, 0),
        "source_state": "resolved",
        "source": "vehiculos.tipo_cliente='mensual' AND activo=1",
    }


def build_historical_completeness(status="complete", missing_ranges=None, unavailable_inputs=None) -> Dict[str, Any]:
    if status not in COMPLETENESS_STATUSES:
        raise ValueError("UNSUPPORTED_COMPLETENESS_STATUS")
    return {
        "status": status,
        "missing_ranges": list(missing_ranges or []),
        "unavailable_inputs": list(unavailable_inputs or []),
    }


def build_plate_history_response(plate, bounds, rows=None, coverage=None) -> Dict[str, Any]:
    rows = rows or []
    coverage = coverage or {}
    timeline = [_build_plate_timeline_row(plate, row) for row in rows]
    timeline.sort(key=_plate_timeline_sort_key)
    source_coverage = [
        {"source": source, "state": state}
        for source, state in sorted(coverage.items())
    ]
    completeness = _plate_history_completeness(source_coverage)

    return {
        "plate": str(plate or "").upper().replace(" ", "").replace("-", ""),
        "bounds": {
            "start": _iso(bounds["start"]),
            "end": _iso(bounds["end"]),
            "limit": bounds.get("limit", 500),
        },
        "timeline": timeline,
        "anomaly_summary": _plate_history_anomaly_summary(source_coverage),
        "statistics": {
            "timeline_row_count": len(timeline),
            "total_amount": _sum_amount(timeline),
            "sources_with_rows": sorted({row["source"] for row in timeline}),
        },
        "source_coverage": source_coverage,
        "historical_completeness": completeness,
    }


def build_closed_report(
    closure,
    vehicle_movements,
    expenses=None,
    mensualidades=None,
    active_monthly_customers=None,
    historical_completeness=None,
) -> Dict[str, Any]:
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
        "mensualidad_sales_total": int(closure.get("mensualidad_sales_total") or 0),
    }
    closure_metrics["operational_net_total"] = (
        closure_metrics["operational_income_total"]
        + closure_metrics["mensualidad_sales_total"]
        - closure_metrics["operational_expense_total"]
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
        "capacity": build_capacity(active_monthly_customers),
        "historical_completeness": historical_completeness or build_historical_completeness(),
        "operation_drill_down": _operation_drill_down(vehicle_movements, expenses or [], period),
        "discrepancy": {
            "status": "none" if all(value == 0 for value in discrepancy_metrics.values()) else "delta",
            "metrics": discrepancy_metrics,
            "compared_sources": ["closure_reference", "operational_rows"],
        },
        "source_state": "closed_snapshot_with_operational_drill_down",
    }


def build_audit_inventory(period_id: str, coverage=None) -> Dict[str, Any]:
    coverage = coverage or {
        "closures": COVERAGE_AVAILABLE,
        "operational_rows": COVERAGE_AVAILABLE,
        "payments": COVERAGE_AVAILABLE,
        "expenses": COVERAGE_AVAILABLE,
        "print_jobs": COVERAGE_PARTIAL,
        "users": COVERAGE_AVAILABLE,
        "operator_sessions": COVERAGE_PARTIAL,
        "parking": COVERAGE_AVAILABLE,
        "solo_wash": COVERAGE_AVAILABLE,
        "monthly_payment": COVERAGE_AVAILABLE,
        "night_charge": COVERAGE_AVAILABLE,
        "closure": COVERAGE_AVAILABLE,
        "logical_deletion": COVERAGE_AVAILABLE,
    }
    available_sources = [source for source, state in coverage.items() if state in {COVERAGE_AVAILABLE, COVERAGE_PARTIAL}]
    unavailable_sources = [source for source, state in coverage.items() if state == COVERAGE_UNAVAILABLE]
    return {
        "period_id": period_id,
        "coverage": [{"source": source, "state": state} for source, state in coverage.items()],
        "available_sources": available_sources,
        "unavailable_sources": unavailable_sources,
        "unavailable_history": ["before_first_closure", "after_current_rows"],
        "requires_event_sourcing": False,
        "unsupported_behaviors": list(AUDIT_INVENTORY_UNSUPPORTED_BEHAVIORS),
    }


def build_report_export(report, export_format: str, generated_at: datetime) -> Dict[str, Any]:
    normalized_format = export_format.lower()
    if normalized_format not in CANONICAL_EXPORT_FORMATS | LEGACY_EXPORT_FORMATS:
        raise ValueError("UNSUPPORTED_EXPORT_FORMAT")

    metadata = {
        "report_id": report["report_id"],
        "format": normalized_format,
        "period_start": report["period"]["start"],
        "period_end": report["period"]["end"],
        "closure_reference_id": report["closure_reference"]["id"],
        "totals": report["closure_reference"]["metrics"].copy(),
        "historical_completeness": report.get("historical_completeness", build_historical_completeness()),
        "generated_at": _iso(generated_at),
        "metric_catalog_version": report["catalog_version"],
        "filters": report.get("filters", {}),
        "source_state": report["source_state"],
        "template_version": "reporting-export-2026-09-29",
        "compatibility": "legacy-only" if normalized_format == "csv" else "canonical",
    }

    if normalized_format == "csv":
        content = _render_csv_export(metadata, report)
        content_type = "text/csv"
    elif normalized_format == "pdf":
        content = _render_pdf_export(metadata, report)
        content_type = "application/pdf"
    else:
        content = _render_xlsx_export(metadata, report)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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


def _build_plate_timeline_row(plate, row):
    item = {
        "source": row["source"],
        "plate": str(row.get("plate") or plate or "").upper().replace(" ", "").replace("-", ""),
        "occurred_at": _iso(row.get("occurred_at")),
        "period": row.get("period"),
        "amount": int(row.get("amount") or 0) if row.get("amount") is not None else None,
        "closure_id": row.get("closure_id"),
    }
    if "id" in row:
        item["id"] = row["id"]
    return item


def _plate_timeline_sort_key(row):
    business_time = row.get("occurred_at") or row.get("period") or ""
    return (business_time, row.get("source") or "", row.get("id") or 0)


def _plate_history_completeness(source_coverage):
    partial_sources = [item["source"] for item in source_coverage if item["state"] == COVERAGE_PARTIAL]
    unavailable_sources = [item["source"] for item in source_coverage if item["state"] == COVERAGE_UNAVAILABLE]
    if unavailable_sources:
        status = "unavailable"
    elif partial_sources:
        status = "partial"
    else:
        status = "complete"
    return build_historical_completeness(
        status=status,
        missing_ranges=partial_sources,
        unavailable_inputs=unavailable_sources,
    )


def _plate_history_anomaly_summary(source_coverage):
    anomalies = []
    partial_sources = [item["source"] for item in source_coverage if item["state"] == COVERAGE_PARTIAL]
    unavailable_sources = [item["source"] for item in source_coverage if item["state"] == COVERAGE_UNAVAILABLE]
    if partial_sources:
        anomalies.append({"code": "source_partial", "sources": partial_sources, "severity": "info"})
    if unavailable_sources:
        anomalies.append({"code": "source_unavailable", "sources": unavailable_sources, "severity": "info"})
    return anomalies


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
            f"Completeness: {metadata['historical_completeness']['status']}",
            f"Operational Income Total: {metrics['operational_income_total']}",
            f"Operational Expense Total: {metrics['operational_expense_total']}",
            f"Mensualidad Sales Total: {metrics['mensualidad_sales_total']}",
            f"Operational Net Total: {metrics['operational_net_total']}",
        ]
    )


def _render_xlsx_export(metadata, report):
    metrics = report["closure_reference"]["metrics"]
    rows = [
        ["report_id", metadata["report_id"]],
        ["period_start", metadata["period_start"]],
        ["period_end", metadata["period_end"]],
        ["closure_reference_id", metadata["closure_reference_id"]],
        ["format", metadata["format"]],
        ["completeness", metadata["historical_completeness"]["status"]],
        ["operational_income_total", metrics["operational_income_total"]],
        ["operational_expense_total", metrics["operational_expense_total"]],
        ["mensualidad_sales_total", metrics["mensualidad_sales_total"]],
        ["operational_net_total", metrics["operational_net_total"]],
    ]
    return "\n".join(f"{key}\t{value}" for key, value in rows)


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
