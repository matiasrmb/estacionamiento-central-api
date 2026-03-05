from datetime import datetime
from typing import Any, Dict

from app.repositories.configuracion_repo import get_all_config
from app.repositories.tarifas_repo import list_tarifas_personalizadas


def _minutes_between(start: datetime, end: datetime) -> int:
    secs = (end - start).total_seconds()
    if secs < 0:
        return 0
    # redondeo hacia arriba por minuto para cobro conservador
    minutes = int((secs + 59) // 60)
    return minutes


def calcular_monto_preview(fecha_hora_ingreso: datetime, now: datetime) -> Dict[str, Any]:
    """
    Cálculo MVP:
    1) Si existen tarifas_personalizadas -> usar tramo donde minutes cae.
    2) Si no, usar configuracion:
       - tarifa_por_minuto (si existe) * minutes
       - o tarifa_hora (si existe) prorrateada por minuto
       - mínimo tarifa_minima si existe
    Devuelve monto y detalle.
    """
    minutes = _minutes_between(fecha_hora_ingreso, now)

    tramos = list_tarifas_personalizadas()
    if tramos:
        monto = None
        tramo_aplicado = None
        for t in tramos:
            if minutes >= int(t["minuto_inicio"]) and minutes <= int(t["minuto_fin"]):
                monto = int(t["valor"])
                tramo_aplicado = f'{t["minuto_inicio"]}-{t["minuto_fin"]}'
                break
        if monto is None:
            # si excede, aplicar último tramo
            last = tramos[-1]
            monto = int(last["valor"])
            tramo_aplicado = f'{last["minuto_inicio"]}-{last["minuto_fin"]}'

        return {
            "minutos_cobrados": minutes,
            "monto": monto,
            "detalle": {
                "modo_tarifa": "TRAMOS",
                "tramo_aplicado": tramo_aplicado,
                "subida_precios_aplicada": False,
                "recargo_monto": 0,
            },
        }

    cfg = get_all_config()

    tarifa_minima = int(cfg.get("tarifa_minima", "0") or "0")
    tarifa_por_minuto = cfg.get("tarifa_por_minuto")
    tarifa_hora = cfg.get("tarifa_hora")

    monto = 0

    if tarifa_por_minuto is not None:
        rate = float(tarifa_por_minuto)
        monto = int(round(rate * minutes))
        modo = "MINUTO"
    elif tarifa_hora is not None:
        rate_h = float(tarifa_hora)
        rate_m = rate_h / 60.0
        monto = int(round(rate_m * minutes))
        modo = "AUTO"
    else:
        # fallback conservador
        monto = tarifa_minima
        modo = "AUTO"

    if monto < tarifa_minima:
        monto = tarifa_minima

    return {
        "minutos_cobrados": minutes,
        "monto": int(monto),
        "detalle": {
            "modo_tarifa": modo,
            "tramo_aplicado": None,
            "subida_precios_aplicada": False,
            "recargo_monto": 0,
        },
    }