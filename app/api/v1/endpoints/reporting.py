from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import require_role
from app.repositories.reporting_read_models import (
    build_metric_catalog,
    build_report_export,
    validate_operation_filters,
    validate_operation_pagination,
    validate_operation_sort,
)
from app.repositories.reporting_repo import get_audit_inventory as get_persisted_audit_inventory
from app.repositories.reporting_repo import get_closed_report as get_persisted_closed_report
from app.repositories.reporting_repo import get_open_dashboard
from app.repositories.reporting_repo import list_operation_rows as list_persisted_operation_rows


router = APIRouter(prefix="/reporting", tags=["reporting"])

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
    category: str | None = None,
    operator: str | None = None,
    plate: str | None = None,
    sort: str | None = None,
    direction: str | None = None,
    limit: str | None = None,
    offset: str | None = None,
    _user=Depends(require_role("admin")),
):
    unsupported_keys = set(request.query_params.keys()) - OPERATION_QUERY_KEYS
    if unsupported_keys:
        raise HTTPException(status_code=422, detail="UNSUPPORTED_OPERATION_QUERY")

    try:
        closure_id = _parse_closure_period_id(period_id)
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
    return get_persisted_audit_inventory(period_id)


def _parse_closure_period_id(period_id: str) -> int:
    if not period_id.startswith("closure:"):
        raise ValueError("UNSUPPORTED_OPERATION_PERIOD")
    raw_id = period_id.split(":", 1)[1]
    try:
        closure_id = int(raw_id)
    except ValueError:
        raise ValueError("UNSUPPORTED_OPERATION_PERIOD")
    if closure_id < 1:
        raise ValueError("UNSUPPORTED_OPERATION_PERIOD")
    return closure_id


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
