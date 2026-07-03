from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn
from app.schemas.wash_pricing import WashPriceSnapshot, WashTypeIn, WashVehicleTypeIn


PARKING_TARIFF_FIELDS = {"tarifa_hora", "tarifa_minima", "valor_minuto", "modo_cobro"}

LEGACY_WASH_CATEGORIES = {
    "lavado_citycar": "CityCar",
    "lavado_suv": "SUV",
    "lavado_camioneta": "Camioneta",
    "lavado_furgon": "Furgón",
    "lavado_minibus": "Mini bus o vehículos grandes",
}

WASH_VEHICLE_TYPE_TABLES = ("tipos_vehiculo_lavado", "tipos_vehiculos_lavado")


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


def list_wash_vehicle_types(table_name: str = "tipos_vehiculo_lavado") -> List[Dict[str, Any]]:
    if table_name not in WASH_VEHICLE_TYPE_TABLES:
        raise ValueError("INVALID_WASH_VEHICLE_TYPE_TABLE")

    with db_conn() as conn:
        rows = conn.execute(text(f"""
            SELECT id_tipo_vehiculo_lavado, codigo, nombre, valor_lavado, activo
            FROM {table_name}
            ORDER BY nombre ASC
        """)).mappings().all()
    return [dict(r) for r in rows]


def list_wash_vehicle_types_for_quotes() -> List[Dict[str, Any]]:
    """Return wash quote options, falling back to legacy configured prices.

    Some deployed databases do not have the newer tipos_vehiculo_lavado table yet.
    Cotizaciones must remain read-only and resilient, so missing/drifted optional
    wash tables fall back to the legacy configuracion keys used by lavado flows.
    """
    for table_name in WASH_VEHICLE_TYPE_TABLES:
        try:
            rows = list_wash_vehicle_types(table_name)
        except Exception as exc:
            if not _looks_like_missing_wash_table(exc):
                raise
            continue
        if any(int(row.get("activo") or 0) for row in rows):
            return rows
    return list_legacy_wash_quote_options()


def list_legacy_wash_quote_options() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(text("""
            SELECT clave, valor
            FROM configuracion
            WHERE clave LIKE 'lavado_%'
        """)).mappings().all()

    configured = {row["clave"]: row["valor"] for row in rows}
    options = []
    for clave, nombre in LEGACY_WASH_CATEGORIES.items():
        monto = _to_positive_int(configured.get(clave))
        if monto is None:
            continue
        options.append({
            "id_tipo_vehiculo_lavado": None,
            "codigo": clave,
            "nombre": nombre,
            "valor_lavado": monto,
            "activo": 1,
            "source": "legacy_configuracion",
        })
    return options


def _to_positive_int(value: Any) -> int | None:
    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _looks_like_missing_wash_table(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(table in message for table in WASH_VEHICLE_TYPE_TABLES) and (
        "doesn't exist" in message or "does not exist" in message or "no such table" in message
    )


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
