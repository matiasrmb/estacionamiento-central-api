from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn
from app.schemas.wash_pricing import WashPriceSnapshot, WashTypeIn, WashVehicleTypeIn


PARKING_TARIFF_FIELDS = {"tarifa_hora", "tarifa_minima", "valor_minuto", "modo_cobro"}


def _as_dict(payload: Any) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    return dict(payload)


def build_wash_vehicle_type_payload(payload: WashVehicleTypeIn | Dict[str, Any]) -> Dict[str, Any]:
    data = _as_dict(payload)
    if PARKING_TARIFF_FIELDS.intersection(data.keys()):
        raise ValueError("PARKING_TARIFF_FIELDS_NOT_ALLOWED")

    return {
        "codigo": str(data["codigo"]).strip(),
        "nombre": str(data["nombre"]).strip(),
        "valor_lavado": int(data["valor_lavado"]),
        "activo": 1 if data.get("activo", True) else 0,
    }


def build_wash_type_payload(payload: WashTypeIn | Dict[str, Any]) -> Dict[str, Any]:
    data = _as_dict(payload)
    return {
        "codigo": str(data["codigo"]).strip(),
        "nombre": str(data["nombre"]).strip(),
        "activo": 1 if data.get("activo", True) else 0,
    }


def build_wash_price_snapshot(wash_vehicle_type: Dict[str, Any]) -> WashPriceSnapshot:
    if not int(wash_vehicle_type.get("activo", 0)):
        raise ValueError("INACTIVE_WASH_VEHICLE_TYPE")

    return WashPriceSnapshot(
        id_tipo_vehiculo_lavado=int(wash_vehicle_type["id_tipo_vehiculo_lavado"]),
        tipo_vehiculo_lavado_snapshot=str(wash_vehicle_type["nombre"]),
        valor_lavado_snapshot=int(wash_vehicle_type["valor_lavado"]),
    )


def resolve_wash_type_delete_action(reference_count: int) -> str:
    return "deactivate" if int(reference_count or 0) > 0 else "delete"


def list_wash_types() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(text("""
            SELECT id_tipo_lavado, codigo, nombre, activo
            FROM tipos_lavado
            ORDER BY nombre ASC
        """)).mappings().all()
    return [dict(r) for r in rows]


def create_wash_type(payload: WashTypeIn) -> int:
    data = build_wash_type_payload(payload)
    with db_conn() as conn:
        conn.execute(text("""
            INSERT INTO tipos_lavado (codigo, nombre, activo)
            VALUES (:codigo, :nombre, :activo)
        """), data)
        conn.commit()
        return int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())


def update_wash_type(id_tipo_lavado: int, payload: WashTypeIn) -> None:
    data = build_wash_type_payload(payload)
    data["id_tipo_lavado"] = id_tipo_lavado
    with db_conn() as conn:
        result = conn.execute(text("""
            UPDATE tipos_lavado
            SET codigo = :codigo, nombre = :nombre, activo = :activo
            WHERE id_tipo_lavado = :id_tipo_lavado
        """), data)
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("WASH_TYPE_NOT_FOUND")


def delete_wash_type(id_tipo_lavado: int) -> str:
    with db_conn() as conn:
        result = conn.execute(
            text("DELETE FROM tipos_lavado WHERE id_tipo_lavado = :id_tipo_lavado"),
            {"id_tipo_lavado": id_tipo_lavado},
        )
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("WASH_TYPE_NOT_FOUND")
    return "deleted"


def list_wash_vehicle_types() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(text("""
            SELECT id_tipo_vehiculo_lavado, codigo, nombre, valor_lavado, activo
            FROM tipos_vehiculo_lavado
            ORDER BY nombre ASC
        """)).mappings().all()
    return [dict(r) for r in rows]


def create_wash_vehicle_type(payload: WashVehicleTypeIn) -> int:
    data = build_wash_vehicle_type_payload(payload)
    with db_conn() as conn:
        conn.execute(text("""
            INSERT INTO tipos_vehiculo_lavado (codigo, nombre, valor_lavado, activo)
            VALUES (:codigo, :nombre, :valor_lavado, :activo)
        """), data)
        conn.commit()
        return int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())


def update_wash_vehicle_type(id_tipo_vehiculo_lavado: int, payload: WashVehicleTypeIn) -> None:
    data = build_wash_vehicle_type_payload(payload)
    data["id_tipo_vehiculo_lavado"] = id_tipo_vehiculo_lavado
    with db_conn() as conn:
        result = conn.execute(text("""
            UPDATE tipos_vehiculo_lavado
            SET codigo = :codigo,
                nombre = :nombre,
                valor_lavado = :valor_lavado,
                activo = :activo
            WHERE id_tipo_vehiculo_lavado = :id_tipo_vehiculo_lavado
        """), data)
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("WASH_VEHICLE_TYPE_NOT_FOUND")


def delete_wash_vehicle_type(id_tipo_vehiculo_lavado: int) -> str:
    with db_conn() as conn:
        refs = conn.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM lavados WHERE id_tipo_vehiculo_lavado = :id) +
                (SELECT COUNT(*) FROM operaciones_servicio WHERE id_tipo_vehiculo_lavado = :id)
        """), {"id": id_tipo_vehiculo_lavado}).scalar()

        action = resolve_wash_type_delete_action(int(refs or 0))
        if action == "deactivate":
            result = conn.execute(text("""
                UPDATE tipos_vehiculo_lavado
                SET activo = 0
                WHERE id_tipo_vehiculo_lavado = :id
            """), {"id": id_tipo_vehiculo_lavado})
            action = "deactivated"
        else:
            result = conn.execute(text("""
                DELETE FROM tipos_vehiculo_lavado
                WHERE id_tipo_vehiculo_lavado = :id
            """), {"id": id_tipo_vehiculo_lavado})
            action = "deleted"

        conn.commit()
        if result.rowcount != 1:
            raise LookupError("WASH_VEHICLE_TYPE_NOT_FOUND")
    return action
