from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_role
from app.repositories.reporting_read_models import (
    build_metric_catalog,
    build_report_export,
)
from app.repositories.reporting_repo import get_audit_inventory as get_persisted_audit_inventory
from app.repositories.reporting_repo import get_closed_report as get_persisted_closed_report
from app.repositories.reporting_repo import get_open_dashboard


router = APIRouter(prefix="/reporting", tags=["reporting"])


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


@router.get("/audit-inventory")
def get_audit_inventory(period_id: str = "current", _user=Depends(require_role("admin"))):
    return get_persisted_audit_inventory(period_id)


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
