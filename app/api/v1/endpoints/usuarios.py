from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_role
from app.repositories.users_repo import (
    create_user,
    list_users,
    update_user_password,
    update_user_status,
)


router = APIRouter(prefix="/usuarios", tags=["usuarios"])


class UsuarioIn(BaseModel):
    usuario: str = Field(..., min_length=1, max_length=50)
    clave: str = Field(..., min_length=1, max_length=200)
    rol: str = Field(..., min_length=1, max_length=20)


class PasswordIn(BaseModel):
    clave: str = Field(..., min_length=1, max_length=200)


class EstadoIn(BaseModel):
    activo: bool


@router.get("")
def listar_usuarios(_user=Depends(require_role("admin"))):
    return {"items": list_users()}


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_usuario(payload: UsuarioIn, _user=Depends(require_role("admin"))):
    try:
        id_usuario = create_user(payload.usuario, payload.clave, payload.rol)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return {"id_usuario": id_usuario}


@router.put("/{usuario}/password")
def cambiar_password(usuario: str, payload: PasswordIn, _user=Depends(require_role("admin"))):
    try:
        update_user_password(usuario, payload.clave)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return {"ok": True}


@router.put("/{usuario}/estado")
def cambiar_estado(usuario: str, payload: EstadoIn, _user=Depends(require_role("admin"))):
    try:
        update_user_status(usuario, payload.activo)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")
    return {"ok": True}
