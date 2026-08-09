from datetime import datetime

from fastapi import APIRouter, Depends

from app.api.deps import require_role
from app.api.v1.endpoints.activos import build_active_items
from app.db.database import db_conn
from app.db.schema_ensure import ensure_monthly_payments_schema, ensure_noches_schema
from app.repositories.cierres_repo import _build_pending_summary


router = APIRouter(tags=["resumen-turno"])


@router.get("/resumen-turno")
def obtener_resumen_turno(_user=Depends(require_role("operador", "admin"))):
    ensure_monthly_payments_schema()
    ensure_noches_schema()
    consultado_a = datetime.now().replace(microsecond=0)

    with db_conn() as conn:
        activos = build_active_items(conn, consultado_a, as_of=consultado_a)
        pendientes = _build_pending_summary(conn, as_of=consultado_a)

    total_general = int(pendientes.get("total_general") or 0)
    total_banos = int(pendientes.get("total_banos_monto") or 0)
    total_actual_caja = int(pendientes.get("total_general") or 0)

    return {
        "consultado_a": consultado_a.isoformat(),
        "vehiculos_activos": len(activos),
        "usos_banos": int(pendientes.get("total_banos") or 0),
        "usos_banos_monto": total_banos,
        "total_turno": total_general,
        "total_actual_caja": total_actual_caja,
        "neto_caja": int(pendientes.get("total_neto") or 0),
    }
