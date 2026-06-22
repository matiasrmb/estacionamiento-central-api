from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_role
from app.repositories.cierres_repo import get_cierre_pendiente, list_cierres, realizar_cierre


router = APIRouter(prefix="/cierres", tags=["cierres"])


@router.get("/pendiente")
def obtener_cierre_pendiente(_user=Depends(require_role("admin"))):
    return get_cierre_pendiente()


@router.get("")
def listar_cierres(_user=Depends(require_role("admin"))):
    return {"items": list_cierres()}


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_cierre(user=Depends(require_role("admin"))):
    try:
        return realizar_cierre(user.get("sub") or "")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="NO_PENDING_CLOSURE")
