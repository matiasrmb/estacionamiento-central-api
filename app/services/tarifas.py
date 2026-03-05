import math
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.engine import Connection


def _get_config_int(conn: Connection, clave: str, default: int) -> int:
    row = conn.execute(
        text("SELECT valor FROM configuracion WHERE clave=:c LIMIT 1"),
        {"c": clave},
    ).fetchone()
    if not row:
        return default
    try:
        return int(float(row[0]))
    except Exception:
        return default


def calcular_monto_mvp(conn: Connection, fecha_ingreso: datetime, fecha_salida: datetime) -> tuple[int, int, str]:
    """
    Retorna (minutos, monto, detalle)

    MVP:
    - minutos = ceil(diff/60)
    - Si hay tramos en tarifas_personalizadas: toma el tramo por minutos
    - Si no, fallback configuracion: tarifa_minima / tarifa_por_hora
    """
    diff = (fecha_salida - fecha_ingreso).total_seconds()
    minutos = max(0, int(math.ceil(diff / 60.0)))

    # 1) Tramos personalizados
    tramo = conn.execute(
        text("""
            SELECT valor, minuto_inicio, minuto_fin
            FROM tarifas_personalizadas
            WHERE :m BETWEEN minuto_inicio AND minuto_fin
            ORDER BY minuto_inicio ASC
            LIMIT 1
        """),
        {"m": minutos},
    ).fetchone()

    if tramo:
        valor, ini, fin = int(tramo[0]), int(tramo[1]), int(tramo[2])
        return minutos, valor, f"Tramo personalizado: {ini}-{fin} min"

    # 2) Fallback configuración
    tarifa_minima = _get_config_int(conn, "tarifa_minima", 300)
    tarifa_hora = _get_config_int(conn, "tarifa_por_hora", 600)

    if minutos <= 60:
        return minutos, tarifa_minima, "MVP: tarifa mínima (<= 60 min)"

    extra_horas = int(math.ceil((minutos - 60) / 60.0))
    monto = tarifa_minima + extra_horas * tarifa_hora
    return minutos, monto, f"MVP: mínima + {extra_horas}h extra"