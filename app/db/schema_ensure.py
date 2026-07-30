import logging
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import Connection

from app.db.database import db_conn

logger = logging.getLogger(__name__)

_ensured_operaciones_servicio = False
_ensured_wash_vehicle_types = False
_ensured_gastos_operacion = False
_ensured_monthly_payments = False

_DUPLICATE_SCHEMA_ERROR_CODES = {1060, 1061}

SOLO_LAVADO_SCHEMA_UNAVAILABLE_MESSAGE = (
    "Solo lavado no disponible: no se pudo actualizar la base de datos. "
    "Contacte soporte / actualice DB."
)

NO_SOLO_LAVADO_PRICE_CONFIG_MESSAGE = (
    "Solo lavado no tiene precios activos configurados. "
    "Configurá o activá un precio/tipo de lavado en Configuración para Solo lavado."
)

LEGACY_WASH_CATEGORIES = {
    "lavado_citycar": "CityCar",
    "lavado_suv": "SUV",
    "lavado_camioneta": "Camioneta",
    "lavado_furgon": "Furgón",
    "lavado_minibus": "Mini bus o vehículos grandes",
}


class SoloLavadoSchemaUnavailable(RuntimeError):
    """Raised when the runtime Solo lavado schema ensure cannot be applied."""


def _is_duplicate_schema_error(exc: DBAPIError) -> bool:
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ()) or ()
    return bool(args and args[0] in _DUPLICATE_SCHEMA_ERROR_CODES)


def _execute_schema(conn: Connection, statement: str) -> None:
    try:
        conn.execute(text(statement))
    except DBAPIError as exc:
        if _is_duplicate_schema_error(exc):
            return
        raise


def _execute_many_schema(conn: Connection, statements: Iterable[str]) -> None:
    for statement in statements:
        _execute_schema(conn, statement)


def ensure_operaciones_servicio_schema() -> None:
    """Ensure solo-lavado service-operation tables/columns exist on deployed DBs."""
    global _ensured_operaciones_servicio
    if _ensured_operaciones_servicio:
        return

    try:
        with db_conn() as conn:
            _ensure_operaciones_servicio_schema_on_connection(conn)
            conn.commit()
    except SoloLavadoSchemaUnavailable:
        raise
    except Exception as exc:
        raise SoloLavadoSchemaUnavailable(SOLO_LAVADO_SCHEMA_UNAVAILABLE_MESSAGE) from exc
    _ensured_operaciones_servicio = True


def ensure_wash_vehicle_type_schema() -> None:
    """Ensure canonical solo-lavado type/pricing table exists and is usable."""
    global _ensured_wash_vehicle_types
    if _ensured_wash_vehicle_types:
        return

    try:
        with db_conn() as conn:
            _ensure_wash_vehicle_type_schema_on_connection(conn)
            conn.commit()
    except SoloLavadoSchemaUnavailable:
        raise
    except Exception as exc:
        raise SoloLavadoSchemaUnavailable(SOLO_LAVADO_SCHEMA_UNAVAILABLE_MESSAGE) from exc
    _ensured_wash_vehicle_types = True


def ensure_gastos_operacion_schema() -> None:
    """Ensure operational expenses and close accounting columns exist."""
    global _ensured_gastos_operacion
    if _ensured_gastos_operacion:
        return

    try:
        with db_conn() as conn:
            _ensure_gastos_operacion_schema_on_connection(conn)
            conn.commit()
    except Exception as exc:
        raise RuntimeError("GASTOS_SCHEMA_UNAVAILABLE") from exc
    _ensured_gastos_operacion = True


def ensure_monthly_payments_schema() -> None:
    """Ensure monthly payment events and their close totals exist."""
    global _ensured_monthly_payments
    if _ensured_monthly_payments:
        return
    try:
        with db_conn() as conn:
            if not _ensured_gastos_operacion:
                _ensure_gastos_operacion_schema_on_connection(conn)
            _ensure_monthly_payments_schema_on_connection(conn)
            conn.commit()
    except Exception as exc:
        raise RuntimeError("MONTHLY_PAYMENTS_SCHEMA_UNAVAILABLE") from exc
    _ensured_monthly_payments = True


def _ensure_wash_vehicle_type_schema_on_connection(conn: Connection) -> None:
    _execute_schema(conn, """
        CREATE TABLE IF NOT EXISTS tipos_vehiculo_lavado (
            id_tipo_vehiculo_lavado INT AUTO_INCREMENT PRIMARY KEY,
            codigo VARCHAR(50) NOT NULL UNIQUE,
            nombre VARCHAR(80) NOT NULL,
            valor_lavado INT NOT NULL,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)
    _copy_plural_wash_vehicle_types_if_present(conn)
    _seed_wash_vehicle_types_from_legacy_config(conn)


def _copy_plural_wash_vehicle_types_if_present(conn: Connection) -> None:
    try:
        conn.execute(text("""
            INSERT INTO tipos_vehiculo_lavado (codigo, nombre, valor_lavado, activo)
            SELECT codigo, nombre, valor_lavado, activo
            FROM tipos_vehiculos_lavado
            ON DUPLICATE KEY UPDATE
                nombre = VALUES(nombre),
                valor_lavado = VALUES(valor_lavado),
                activo = VALUES(activo)
        """))
    except Exception as exc:
        if not _looks_like_missing_wash_type_table(exc):
            raise


def _seed_wash_vehicle_types_from_legacy_config(conn: Connection) -> None:
    rows = conn.execute(text("""
        SELECT clave, valor
        FROM configuracion
        WHERE clave LIKE 'lavado_%'
    """)).mappings().all()
    configured = {row["clave"]: row["valor"] for row in rows}
    for clave, nombre in LEGACY_WASH_CATEGORIES.items():
        amount = _to_positive_int(configured.get(clave))
        if amount is None:
            continue
        conn.execute(text("""
            INSERT INTO tipos_vehiculo_lavado (codigo, nombre, valor_lavado, activo)
            VALUES (:codigo, :nombre, :valor_lavado, TRUE)
            ON DUPLICATE KEY UPDATE
                nombre = VALUES(nombre),
                valor_lavado = VALUES(valor_lavado),
                activo = TRUE
        """), {"codigo": clave, "nombre": nombre, "valor_lavado": amount})


def _to_positive_int(value) -> int | None:
    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _looks_like_missing_wash_type_table(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(table in message for table in ("tipos_vehiculo_lavado", "tipos_vehiculos_lavado")) and (
        "doesn't exist" in message or "does not exist" in message or "no such table" in message
    )


def _ensure_operaciones_servicio_schema_on_connection(conn: Connection) -> None:
    _execute_schema(conn, """
        CREATE TABLE IF NOT EXISTS operaciones_servicio (
            id_operacion_servicio INT AUTO_INCREMENT PRIMARY KEY,
            patente VARCHAR(10) NOT NULL,
            id_tipo_vehiculo_lavado INT NULL,
            tipo_vehiculo_lavado_snapshot VARCHAR(80) NOT NULL,
            valor_lavado_snapshot INT NOT NULL,
            fecha_hora_inicio DATETIME NOT NULL,
            fecha_hora_fin DATETIME NULL,
            duracion_minutos INT NULL,
            usuario_inicio VARCHAR(50) NOT NULL,
            usuario_fin VARCHAR(50) NULL,
            estado ENUM('ACTIVO', 'FINALIZADO_COBRADO', 'CONVERTIDO_ESTADIA') NOT NULL DEFAULT 'ACTIVO',
            id_ingreso_generado INT NULL,
            cerrado BOOLEAN NOT NULL DEFAULT FALSE,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_operaciones_servicio_estado_fecha (estado, fecha_hora_inicio),
            INDEX idx_operaciones_servicio_patente (patente),
            INDEX idx_operaciones_servicio_ingreso_generado (id_ingreso_generado),
            INDEX idx_operaciones_servicio_cierre (cerrado, estado, fecha_hora_fin)
        )
    """)
    _execute_many_schema(conn, [
        "ALTER TABLE operaciones_servicio ADD COLUMN id_tipo_vehiculo_lavado INT NULL",
        "ALTER TABLE operaciones_servicio ADD COLUMN tipo_vehiculo_lavado_snapshot VARCHAR(80) NULL",
        "ALTER TABLE operaciones_servicio ADD COLUMN valor_lavado_snapshot INT NOT NULL DEFAULT 0",
        "ALTER TABLE operaciones_servicio ADD COLUMN fecha_hora_fin DATETIME NULL",
        "ALTER TABLE operaciones_servicio ADD COLUMN duracion_minutos INT NULL",
        "ALTER TABLE operaciones_servicio ADD COLUMN usuario_fin VARCHAR(50) NULL",
        "ALTER TABLE operaciones_servicio ADD COLUMN estado ENUM('ACTIVO', 'FINALIZADO_COBRADO', 'CONVERTIDO_ESTADIA') NOT NULL DEFAULT 'ACTIVO'",
        "ALTER TABLE operaciones_servicio ADD COLUMN id_ingreso_generado INT NULL",
        "ALTER TABLE operaciones_servicio ADD COLUMN cerrado BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE operaciones_servicio ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE operaciones_servicio ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "ALTER TABLE operaciones_servicio ADD INDEX idx_operaciones_servicio_estado_fecha (estado, fecha_hora_inicio)",
        "ALTER TABLE operaciones_servicio ADD INDEX idx_operaciones_servicio_patente (patente)",
        "ALTER TABLE operaciones_servicio ADD INDEX idx_operaciones_servicio_ingreso_generado (id_ingreso_generado)",
        "ALTER TABLE operaciones_servicio ADD INDEX idx_operaciones_servicio_cierre (cerrado, estado, fecha_hora_fin)",
    ])
    _execute_many_schema(conn, [
        "ALTER TABLE cierres_diarios ADD COLUMN total_lavados_solos INT NOT NULL DEFAULT 0",
        "ALTER TABLE cierres_diarios ADD COLUMN total_lavados_solos_monto INT NOT NULL DEFAULT 0",
        "ALTER TABLE cierres_diarios ADD COLUMN total_general INT NOT NULL DEFAULT 0",
    ])


def _ensure_gastos_operacion_schema_on_connection(conn: Connection) -> None:
    _execute_schema(conn, """
        CREATE TABLE IF NOT EXISTS gastos_operacion (
            id_gasto INT AUTO_INCREMENT PRIMARY KEY,
            fecha_hora DATETIME NOT NULL,
            categoria VARCHAR(50) NOT NULL,
            descripcion VARCHAR(500) NOT NULL,
            monto INT NOT NULL,
            usuario VARCHAR(50) NOT NULL,
            id_cierre INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_gastos_operacion_pendiente (id_cierre, fecha_hora),
            INDEX idx_gastos_operacion_cierre (id_cierre),
            CONSTRAINT fk_gastos_operacion_cierre
                FOREIGN KEY (id_cierre) REFERENCES cierres_diarios(id_cierre)
                ON DELETE RESTRICT
        )
    """)
    _execute_many_schema(conn, [
        "ALTER TABLE cierres_diarios ADD COLUMN total_gastos INT NOT NULL DEFAULT 0",
        "ALTER TABLE cierres_diarios ADD COLUMN total_neto INT NOT NULL DEFAULT 0",
        "ALTER TABLE usos_bano ADD COLUMN id_cierre INT NULL",
        "ALTER TABLE usos_bano ADD INDEX idx_usos_bano_pendiente (id_cierre, fecha_hora)",
        "ALTER TABLE usos_bano ADD INDEX idx_usos_bano_cierre (id_cierre)",
    ])


def _ensure_monthly_payments_schema_on_connection(conn: Connection) -> None:
    _execute_many_schema(conn, [
        "ALTER TABLE vehiculos ADD COLUMN dia_vencimiento TINYINT UNSIGNED NOT NULL DEFAULT 1",
        "ALTER TABLE vehiculos ADD COLUMN telefono VARCHAR(30) NULL",
        "ALTER TABLE cierres_diarios ADD COLUMN total_mensualidades INT NOT NULL DEFAULT 0",
        "ALTER TABLE cierres_diarios ADD COLUMN total_mensualidades_monto INT NOT NULL DEFAULT 0",
    ])
    _execute_schema(conn, """
        CREATE TABLE IF NOT EXISTS pagos_mensuales (
            id_pago_mensual INT AUTO_INCREMENT PRIMARY KEY,
            id_vehiculo INT NOT NULL,
            periodo DATE NOT NULL,
            dia_vencimiento_snapshot TINYINT UNSIGNED NOT NULL,
            monto_snapshot INT NOT NULL,
            fecha_pago DATETIME NOT NULL,
            usuario VARCHAR(50) NOT NULL,
            metodo_pago VARCHAR(40) NULL,
            observacion VARCHAR(500) NULL,
            id_cierre INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_pagos_mensuales_vehiculo_periodo (id_vehiculo, periodo),
            INDEX idx_pagos_mensuales_pendiente_cierre (id_cierre, fecha_pago),
            INDEX idx_pagos_mensuales_periodo (periodo),
            CONSTRAINT fk_pagos_mensuales_vehiculo
                FOREIGN KEY (id_vehiculo) REFERENCES vehiculos(id_vehiculo),
            CONSTRAINT fk_pagos_mensuales_cierre
                FOREIGN KEY (id_cierre) REFERENCES cierres_diarios(id_cierre)
        )
    """)
