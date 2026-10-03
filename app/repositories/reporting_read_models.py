from datetime import datetime
from typing import Any, Dict, Iterable, List


METRIC_CATALOG_VERSION = "2026-09-29"
TOTAL_PARKING_SPACES = 50
COMPLETENESS_STATUSES = {"complete", "partial", "unavailable"}
CANONICAL_EXPORT_FORMATS = {"pdf", "xlsx"}
LEGACY_EXPORT_FORMATS = {"csv"}
DEFAULT_OPERATION_LIMIT = 100
MAX_OPERATION_LIMIT = 200
ALLOWED_OPERATION_FILTERS = {"category", "operator", "plate"}
ALLOWED_OPERATION_CATEGORIES = {"vehicle_movement", "operational_expense", "mensualidad_sale"}
ALLOWED_OPERATION_SORTS = {"occurred_at", "amount", "category"}
ALLOWED_SORT_DIRECTIONS = {"asc", "desc"}

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


def validate_operation_filters(filters=None) -> Dict[str, str]:
    filters = filters or {}
    validated = {}

    for key, value in filters.items():
        if key not in ALLOWED_OPERATION_FILTERS:
            raise ValueError("UNSUPPORTED_OPERATION_FILTER")
        normalized_value = str(value).strip() if value is not None else ""
        if not normalized_value:
            raise ValueError("INVALID_OPERATION_FILTER_VALUE")
        if key == "category" and normalized_value not in ALLOWED_OPERATION_CATEGORIES:
            raise ValueError("INVALID_OPERATION_FILTER_VALUE")
        validated[key] = normalized_value

    return validated


def validate_operation_sort(sort=None, direction=None) -> Dict[str, str]:
    normalized_sort = (sort or "occurred_at").strip()
    normalized_direction = (direction or "asc").strip().lower()

    if normalized_sort not in ALLOWED_OPERATION_SORTS:
        raise ValueError("UNSUPPORTED_OPERATION_SORT")
    if normalized_direction not in ALLOWED_SORT_DIRECTIONS:
        raise ValueError("UNSUPPORTED_OPERATION_SORT_DIRECTION")

    return {
        "field": normalized_sort,
        "direction": normalized_direction,
        "tie_breaker": "operation_id",
    }


def validate_operation_pagination(limit=None, offset=None) -> Dict[str, int]:
    parsed_limit = _parse_non_negative_int(limit, DEFAULT_OPERATION_LIMIT, "INVALID_OPERATION_LIMIT")
    parsed_offset = _parse_non_negative_int(offset, 0, "INVALID_OPERATION_OFFSET")

    if parsed_limit < 1 or parsed_limit > MAX_OPERATION_LIMIT:
        raise ValueError("INVALID_OPERATION_LIMIT")

    return {"limit": parsed_limit, "offset": parsed_offset}


def build_operation_pagination_metadata(total: int, limit: int, offset: int) -> Dict[str, Any]:
    next_offset = offset + limit
    has_more = next_offset < total

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
    }


def serialize_operation_row(row) -> Dict[str, Any]:
    source = row.get("source") or row.get("category")
    source_id = row.get("source_id") or row.get("id")
    operation_id = row.get("operation_id") or f"{source}:{source_id}"

    return {
        "operation_id": operation_id,
        "occurred_at": _iso(row.get("occurred_at")),
        "amount": int(row.get("amount") or 0),
        "category": row.get("category"),
        "operator": row.get("operator"),
        "plate": row.get("plate"),
        "description": row.get("description"),
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
        "closures": "available",
        "operational_rows": "available",
        "payments": "available",
        "expenses": "available",
        "print_jobs": "partial",
        "users": "available",
        "operator_sessions": "partial",
    }
    available_sources = [source for source, state in coverage.items() if state in {"available", "partial"}]
    unavailable_sources = [source for source, state in coverage.items() if state == "unavailable"]
    return {
        "period_id": period_id,
        "coverage": [{"source": source, "state": state} for source, state in coverage.items()],
        "available_sources": available_sources,
        "unavailable_sources": unavailable_sources,
        "unavailable_history": ["before_first_closure", "after_current_rows"],
        "requires_event_sourcing": False,
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


def _parse_non_negative_int(value, default, error_code):
    if value is None:
        return default
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        raise ValueError(error_code)
    if parsed_value < 0:
        raise ValueError(error_code)
    return parsed_value


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
