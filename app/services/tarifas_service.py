from datetime import datetime
from typing import Any, Dict

from app.db.database import db_conn
from app.services.tarifas import calcular_monto_desde_minutos


def _minutes_between(start: datetime, end: datetime) -> int:
    secs = (end - start).total_seconds()
    if secs < 0:
        return 0
    # redondeo hacia arriba por minuto para cobro conservador
    minutes = int((secs + 59) // 60)
    return minutes


def calcular_monto_preview(fecha_hora_ingreso: datetime, now: datetime) -> Dict[str, Any]:
    """
    Devuelve una cotización no persistente usando la misma lógica tarifaria que
    la preview/confirmación de salida normal.
    """
    minutes = _minutes_between(fecha_hora_ingreso, now)
    with db_conn() as conn:
        minutos, monto, detalle = calcular_monto_desde_minutos(
            conn,
            minutes,
            fecha_hora_ingreso,
            now,
        )

    return {
        "minutos_cobrados": minutos,
        "monto": monto,
        "detalle": {
            "modo_tarifa": detalle,
            "tramo_aplicado": None,
            "subida_precios_aplicada": False,
            "recargo_monto": 0,
        },
    }
