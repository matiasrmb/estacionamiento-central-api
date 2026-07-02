from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_role
from app.repositories.wash_pricing_repo import (
    create_wash_type as repo_create_wash_type,
    create_wash_vehicle_type as repo_create_wash_vehicle_type,
    delete_wash_type as repo_delete_wash_type,
    delete_wash_vehicle_type as repo_delete_wash_vehicle_type,
    list_wash_types as repo_list_wash_types,
    list_wash_vehicle_types as repo_list_wash_vehicle_types,
    update_wash_type as repo_update_wash_type,
    update_wash_vehicle_type as repo_update_wash_vehicle_type,
)
from app.schemas.wash_pricing import WashTypeIn, WashVehicleTypeIn


router = APIRouter(tags=["wash-pricing"])


def _handle_wash_pricing_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.get("/tipos-lavado")
def listar_tipos_lavado(_user=Depends(require_role("admin"))):
    return {"items": repo_list_wash_types()}


@router.post("/tipos-lavado", status_code=status.HTTP_201_CREATED)
def crear_tipo_lavado(payload: WashTypeIn, _user=Depends(require_role("admin"))):
    try:
        new_id = repo_create_wash_type(payload)
    except Exception as exc:
        _handle_wash_pricing_error(exc)
    return {"id_tipo_lavado": new_id}


@router.put("/tipos-lavado/{id_tipo_lavado}")
def actualizar_tipo_lavado(id_tipo_lavado: int, payload: WashTypeIn, _user=Depends(require_role("admin"))):
    try:
        repo_update_wash_type(id_tipo_lavado, payload)
    except Exception as exc:
        _handle_wash_pricing_error(exc)
    return {"ok": True}


@router.delete("/tipos-lavado/{id_tipo_lavado}")
def eliminar_tipo_lavado(id_tipo_lavado: int, _user=Depends(require_role("admin"))):
    try:
        action = repo_delete_wash_type(id_tipo_lavado)
    except Exception as exc:
        _handle_wash_pricing_error(exc)
    return {"ok": True, "action": action}


@router.get("/tipos-vehiculo-lavado")
def listar_tipos_vehiculo_lavado(_user=Depends(require_role("admin"))):
    return {"items": repo_list_wash_vehicle_types()}


@router.post("/tipos-vehiculo-lavado", status_code=status.HTTP_201_CREATED)
def crear_tipo_vehiculo_lavado(payload: WashVehicleTypeIn, _user=Depends(require_role("admin"))):
    try:
        new_id = repo_create_wash_vehicle_type(payload)
    except Exception as exc:
        _handle_wash_pricing_error(exc)
    return {"id_tipo_vehiculo_lavado": new_id}


@router.put("/tipos-vehiculo-lavado/{id_tipo_vehiculo_lavado}")
def actualizar_tipo_vehiculo_lavado(
    id_tipo_vehiculo_lavado: int,
    payload: WashVehicleTypeIn,
    _user=Depends(require_role("admin")),
):
    try:
        repo_update_wash_vehicle_type(id_tipo_vehiculo_lavado, payload)
    except Exception as exc:
        _handle_wash_pricing_error(exc)
    return {"ok": True}


@router.delete("/tipos-vehiculo-lavado/{id_tipo_vehiculo_lavado}")
def eliminar_tipo_vehiculo_lavado(id_tipo_vehiculo_lavado: int, _user=Depends(require_role("admin"))):
    try:
        action = repo_delete_wash_vehicle_type(id_tipo_vehiculo_lavado)
    except Exception as exc:
        _handle_wash_pricing_error(exc)
    return {"ok": True, "action": action}
