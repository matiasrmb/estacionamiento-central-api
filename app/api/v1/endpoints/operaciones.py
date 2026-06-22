from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.operaciones_repo import (
    finalizar_lavado,
    iniciar_lavado,
    list_lavado_categorias,
    registrar_uso_bano,
)


router = APIRouter(tags=["operaciones"])


class BanoIn(BaseModel):
    monto: int | None = Field(default=None, ge=0)


class IniciarLavadoIn(BaseModel):
    id_ingreso: int = Field(..., ge=1)
    categoria_lavado: str = Field(..., min_length=1, max_length=50)


class FinalizarLavadoIn(BaseModel):
    id_ingreso: int = Field(..., ge=1)


@router.post("/banos", status_code=status.HTTP_201_CREATED)
def registrar_bano(payload: BanoIn, user=Depends(require_role("operador", "admin"))):
    return registrar_uso_bano(payload.monto, user.get("sub") or "")


@router.get("/lavados/categorias")
def listar_lavado_categorias(_user=Depends(require_role("operador", "admin"))):
    return {"items": list_lavado_categorias()}


@router.post("/lavados/iniciar", status_code=status.HTTP_201_CREATED)
def iniciar_lavado_endpoint(payload: IniciarLavadoIn, user=Depends(require_role("operador", "admin"))):
    try:
        return iniciar_lavado(payload.id_ingreso, payload.categoria_lavado, user.get("sub") or "")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="INGRESO_NOT_FOUND")
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/lavados/finalizar")
def finalizar_lavado_endpoint(payload: FinalizarLavadoIn, user=Depends(require_role("operador", "admin"))):
    try:
        return finalizar_lavado(payload.id_ingreso, user.get("sub") or "")
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ACTIVE_WASH_NOT_FOUND")
