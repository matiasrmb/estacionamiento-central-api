from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_role
from app.repositories.asistencias_repo import obtener_asistencias


router = APIRouter(prefix="/asistencias", tags=["asistencias"])


@router.get("")
def listar_asistencias(
    usuario: str = "",
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    _user=Depends(require_role("admin")),
):
    return obtener_asistencias(usuario, fecha_inicio, fecha_fin)
