import logging
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import Connection

from app.db.database import db_conn

logger = logging.getLogger(__name__)

_ensured_gastos_operacion = False
_ensured_monthly_payments = False
_ensured_noches = False

_DUPLICATE_SCHEMA_ERROR_CODES = {1060, 1061}

SOLO_LAVADO_SCHEMA_UNAVAILABLE_MESSAGE = (
    "Solo lavado no disponible: no se pudo actualizar la base de datos. "
    "Contacte soporte / actualice DB."
)

NO_SOLO_LAVADO_PRICE_CONFIG_MESSAGE = (
    "Solo lavado no tiene precios activos configurados. "
    "Configurá o activá un precio/tipo de lavado en Configuración para Solo lavado."
)

class SoloLavadoSchemaUnavailable(RuntimeError):
    """Raised when the required Solo lavado schema is unavailable."""


def raise_if_missing_solo_lavado_schema(exc: Exception) -> None:
    """Translate a missing canonical wash pricing table error without modifying the DB."""
    message = str(exc).casefold()
    if "tipos_vehiculo_lavado" in message and any(
        marker in message
        for marker in ("doesn't exist", "does not exist", "no such table", "undefined table")
    ):
        raise SoloLavadoSchemaUnavailable(SOLO_LAVADO_SCHEMA_UNAVAILABLE_MESSAGE) from exc


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


def ensure_noches_schema() -> None:
    """Ensure prepaid overnight charges and their default configuration exist."""
    global _ensured_noches
    if _ensured_noches:
        return
    try:
        with db_conn() as conn:
            _ensure_noches_schema_on_connection(conn)
            conn.commit()
    except Exception as exc:
        raise RuntimeError("NOCHES_SCHEMA_UNAVAILABLE") from exc
    _ensured_noches = True


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


def _ensure_noches_schema_on_connection(conn: Connection) -> None:
    _execute_many_schema(conn, [
        "ALTER TABLE cierres_diarios ADD COLUMN total_noches INT NOT NULL DEFAULT 0",
        "ALTER TABLE cierres_diarios ADD COLUMN total_noches_monto INT NOT NULL DEFAULT 0",
    ])
    _execute_schema(conn, """
        CREATE TABLE IF NOT EXISTS cobros_noches (
            id_cobro_noche INT AUTO_INCREMENT PRIMARY KEY,
            id_ingreso INT NOT NULL,
            monto_snapshot INT NOT NULL,
            hora_inicio_snapshot TIME NOT NULL,
            hora_fin_snapshot TIME NOT NULL,
            fecha_hora_pago DATETIME NOT NULL,
            usuario VARCHAR(50) NOT NULL,
            estado ENUM('PAGADO', 'ANULADO') NOT NULL DEFAULT 'PAGADO',
            id_cierre INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_cobros_noches_ingreso (id_ingreso),
            INDEX idx_cobros_noches_pendiente_cierre (id_cierre, fecha_hora_pago),
            CONSTRAINT fk_cobros_noches_ingreso
                FOREIGN KEY (id_ingreso) REFERENCES ingresos(id_ingreso),
            CONSTRAINT fk_cobros_noches_cierre
                FOREIGN KEY (id_cierre) REFERENCES cierres_diarios(id_cierre)
        )
    """)
    _execute_many_schema(conn, [
        "ALTER TABLE cobros_noches ADD COLUMN estado_operativo ENUM('PENDIENTE', 'RETIRADO', 'CONVERTIDO') NOT NULL DEFAULT 'PENDIENTE'",
        "ALTER TABLE cobros_noches ADD COLUMN fecha_hora_resolucion DATETIME NULL",
        "ALTER TABLE cobros_noches ADD INDEX idx_cobros_noches_estado_operativo (estado_operativo, id_ingreso)",
    ])
    for clave, valor in {
        "noches_activo": "0",
        "noches_hora_inicio": "19:30",
        "noches_hora_fin": "09:30",
        "noches_valor": "0",
    }.items():
        conn.execute(text("""
            INSERT INTO configuracion (clave, valor)
            VALUES (:clave, :valor)
            ON DUPLICATE KEY UPDATE clave = VALUES(clave)
        """), {"clave": clave, "valor": valor})
