from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_role
from app.repositories.reportes_repo import obtener_reporte


router = APIRouter(prefix="/reportes", tags=["reportes"])


@router.get("/movimientos")
def listar_movimientos(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    patente: str = "",
    _user=Depends(require_role("admin")),
):
    return obtener_reporte(fecha_inicio, fecha_fin, patente)
