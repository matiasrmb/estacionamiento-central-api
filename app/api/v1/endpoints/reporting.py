from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import require_role
from app.core.plates import require_valid_plate
from app.repositories.reporting_read_models import (
    build_metric_catalog,
    build_report_export,
    validate_operation_filters,
    validate_operation_pagination,
    validate_operation_sort,
)
from app.repositories.reporting_repo import get_audit_inventory as get_persisted_audit_inventory
from app.repositories.reporting_repo import get_closed_report as get_persisted_closed_report
from app.repositories.reporting_repo import get_closed_period_operation_rows as list_persisted_operation_rows
from app.repositories.reporting_repo import get_open_dashboard
from app.repositories.reporting_repo import get_plate_history as get_persisted_plate_history


router = APIRouter(prefix="/reporting", tags=["reporting"])
MAX_PLATE_HISTORY_WINDOW = timedelta(days=366)
MAX_PLATE_HISTORY_LIMIT = 500
OPERATION_QUERY_KEYS = {"period_id", "category", "operator", "plate", "sort", "direction", "limit", "offset"}


@router.get("/metric-catalog")
def get_metric_catalog(_user=Depends(require_role("admin"))):
    return build_metric_catalog()


@router.get("/dashboard")
def get_dashboard(
    unsupported_filter: str = "",
    _user=Depends(require_role("admin")),
):
    if unsupported_filter:
        raise HTTPException(status_code=422, detail="UNSUPPORTED_REPORTING_FILTER")

    return get_open_dashboard()


@router.get("/reports/closed/{closure_id}")
def get_closed_report(closure_id: int, _user=Depends(require_role("admin"))):
    try:
        return get_persisted_closed_report(closure_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports/operations")
def get_operations_report(
    request: Request,
    period_id: str,
    category: Optional[str] = None,
    operator: Optional[str] = None,
    plate: Optional[str] = None,
    sort: Optional[str] = None,
    direction: Optional[str] = None,
    limit: Optional[str] = None,
    offset: Optional[str] = None,
    _user=Depends(require_role("admin")),
):
    try:
        _validate_operation_query_keys(request)
        closure_id = _parse_operation_closure_period_id(period_id)
        filters = validate_operation_filters(
            {key: value for key, value in {"category": category, "operator": operator, "plate": plate}.items() if value is not None}
        )
        validated_sort = validate_operation_sort(sort, direction)
        pagination = validate_operation_pagination(limit, offset)
        return list_persisted_operation_rows(
            closure_id,
            filters=filters,
            sort=validated_sort,
            pagination=pagination,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/audit-inventory")
def get_audit_inventory(period_id: str = "current", _user=Depends(require_role("admin"))):
    validate_reporting_period_id(period_id)
    return get_persisted_audit_inventory(period_id)


@router.get("/plates/{plate}/history")
def get_plate_history(
    plate: str,
    start: str = "",
    end: str = "",
    limit: int = MAX_PLATE_HISTORY_LIMIT,
    _user=Depends(require_role("admin")),
):
    normalized_plate, bounds = validate_plate_history_request(plate, start, end, limit)
    try:
        return get_persisted_plate_history(
            normalized_plate,
            start=bounds["start"],
            end=bounds["end"],
            limit=bounds["limit"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def validate_plate_history_request(plate: str, start: str, end: str, limit: int):
    try:
        normalized_plate = require_valid_plate(plate)
        bounds = _parse_plate_history_bounds(start, end)
        if not 1 <= int(limit) <= MAX_PLATE_HISTORY_LIMIT:
            raise ValueError("INVALID_HISTORY_LIMIT")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return normalized_plate, {"start": bounds["start"], "end": bounds["end"], "limit": int(limit)}


def validate_reporting_period_id(period_id: str):
    if period_id == "current":
        return
    if not period_id or ":" not in period_id:
        raise HTTPException(status_code=422, detail="INVALID_PERIOD_ID")

    prefix, value = period_id.split(":", 1)
    if prefix == "closure" and value.isdigit() and int(value) > 0:
        return
    if prefix == "open" and (value == "initial" or (value.isdigit() and int(value) > 0)):
        return
    raise HTTPException(status_code=422, detail="INVALID_PERIOD_ID")


def _parse_operation_closure_period_id(period_id: str) -> int:
    if not period_id or ":" not in period_id:
        raise ValueError("UNSUPPORTED_OPERATION_PERIOD")
    prefix, value = period_id.split(":", 1)
    if prefix == "closure" and value.isdigit() and int(value) > 0:
        return int(value)
    raise ValueError("UNSUPPORTED_OPERATION_PERIOD")


def _validate_operation_query_keys(request: Request):
    for key in request.query_params.keys():
        if key not in OPERATION_QUERY_KEYS:
            raise ValueError("UNSUPPORTED_OPERATION_QUERY")


def _parse_plate_history_bounds(start: str, end: str):
    if not start or not end:
        raise ValueError("MISSING_HISTORY_BOUNDS")
    try:
        parsed_start = datetime.fromisoformat(start)
        parsed_end = datetime.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("INVALID_HISTORY_BOUNDS") from exc
    if parsed_start >= parsed_end:
        raise ValueError("INVALID_HISTORY_BOUNDS")
    if parsed_end - parsed_start > MAX_PLATE_HISTORY_WINDOW:
        raise ValueError("HISTORY_WINDOW_TOO_LARGE")
    return {"start": parsed_start, "end": parsed_end}


@router.get("/exports/{closure_id}.{export_format}")
def export_closed_report(closure_id: int, export_format: str, _user=Depends(require_role("admin"))):
    try:
        from datetime import datetime, timezone

        return build_report_export(
            get_persisted_closed_report(closure_id), export_format, generated_at=datetime.now(timezone.utc)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
