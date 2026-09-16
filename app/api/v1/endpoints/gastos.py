from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_role
from app.repositories.gastos_repo import (
    GastoCerradoError,
    GastoNotFoundError,
    crear_gasto,
    editar_gasto,
    eliminar_gasto,
    list_gastos_pendientes,
)
from app.schemas.gastos import GastoCreateIn, GastoDeleteIn, GastoUpdateIn


router = APIRouter(prefix="/gastos", tags=["gastos"])


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_gasto_endpoint(payload: GastoCreateIn, user=Depends(require_role("operador", "admin"))):
    if not payload.confirmado:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CONFIRMATION_REQUIRED")
    return crear_gasto(
        payload.categoria,
        payload.descripcion,
        payload.monto,
        user.get("sub") or "",
    )


@router.get("/pendientes")
def listar_gastos_pendientes(_user=Depends(require_role("operador", "admin"))):
    return list_gastos_pendientes()


@router.patch("/{id_gasto}")
def editar_gasto_endpoint(id_gasto: int, payload: GastoUpdateIn, user=Depends(require_role("admin"))):
    if not payload.confirmado:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CONFIRMATION_REQUIRED")
    try:
        return editar_gasto(
            id_gasto,
            payload.categoria,
            payload.descripcion,
            payload.monto,
            user.get("sub") or "",
        )
    except GastoNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GASTO_NOT_FOUND")
    except GastoCerradoError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="GASTO_ALREADY_CLOSED")


@router.delete("/{id_gasto}")
def eliminar_gasto_endpoint(id_gasto: int, payload: GastoDeleteIn, user=Depends(require_role("admin"))):
    if not payload.confirmado:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CONFIRMATION_REQUIRED")
    try:
        return eliminar_gasto(id_gasto, user.get("sub") or "")
    except GastoNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GASTO_NOT_FOUND")
    except GastoCerradoError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="GASTO_ALREADY_CLOSED")
