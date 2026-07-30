from fastapi import APIRouter, Depends, status

from app.api.deps import require_role
from app.repositories.gastos_repo import crear_gasto, list_gastos_pendientes
from app.schemas.gastos import GastoCreateIn


router = APIRouter(prefix="/gastos", tags=["gastos"])


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_gasto_endpoint(payload: GastoCreateIn, user=Depends(require_role("admin"))):
    return crear_gasto(
        payload.categoria,
        payload.descripcion,
        payload.monto,
        user.get("sub") or "",
    )


@router.get("/pendientes")
def listar_gastos_pendientes(_user=Depends(require_role("admin"))):
    return list_gastos_pendientes()
