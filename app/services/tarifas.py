import math
from datetime import datetime, timedelta
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


def _get_config(conn: Connection) -> dict[str, str]:
    rows = conn.execute(text("SELECT clave, valor FROM configuracion")).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _list_tarifas_personalizadas(conn: Connection) -> list[dict[str, int]]:
    rows = conn.execute(
        text("""
            SELECT minuto_inicio, minuto_fin, valor
            FROM tarifas_personalizadas
            ORDER BY minuto_inicio ASC
        """)
    ).fetchall()
    return [
        {
            "minuto_inicio": int(row[0]),
            "minuto_fin": int(row[1]),
            "valor": int(row[2]),
        }
        for row in rows
    ]


def _get_subida_activa(conn: Connection) -> dict[str, object] | None:
    row = conn.execute(
        text("""
            SELECT hora_inicio, hora_fin, monto_adicional
            FROM subida_precios
            WHERE activa = 1
            ORDER BY id_subida DESC
            LIMIT 1
        """)
    ).fetchone()
    if not row:
        return None
    return {
        "hora_inicio": row[0],
        "hora_fin": row[1],
        "monto_adicional": int(row[2]),
    }


def _time_as_hhmm(value: object) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]


def _calcular_minutos_en_subida(
    fecha_hora_ingreso: datetime,
    fecha_hora_salida: datetime,
    hora_inicio: object,
    hora_fin: object,
) -> int:
    hora_inicio_dt = datetime.combine(
        fecha_hora_ingreso.date(),
        datetime.strptime(_time_as_hhmm(hora_inicio), "%H:%M").time(),
    )
    hora_fin_dt = datetime.combine(
        fecha_hora_ingreso.date(),
        datetime.strptime(_time_as_hhmm(hora_fin), "%H:%M").time(),
    )

    if hora_fin_dt <= hora_inicio_dt:
        hora_fin_dt += timedelta(days=1)

    inicio_real = max(fecha_hora_ingreso, hora_inicio_dt)
    fin_real = min(fecha_hora_salida, hora_fin_dt)

    if inicio_real >= fin_real:
        return 0

    return int((fin_real - inicio_real).total_seconds() / 60)


def calcular_monto_mvp(conn: Connection, fecha_ingreso: datetime, fecha_salida: datetime) -> tuple[int, int, str]:
    """
    Retorna (minutos, monto, detalle)

    Replica la lógica principal del escritorio para mantener cobros consistentes:
    - modo minuto: tarifa mínima + valor por minuto adicional
    - modo personalizado: tramos cíclicos
    - modo auto: bloques por hora usando tarifa mínima
    - subida temporal: recargo según el modo
    """
    diff = (fecha_salida - fecha_ingreso).total_seconds()
    minutos = max(0, int(math.ceil(diff / 60.0)))

    config = _get_config(conn)
    modo = config.get("modo_cobro", "minuto")
    tarifa_minima = int(config.get("tarifa_minima", 300))
    valor_minuto = int(config.get("valor_minuto", 25))
    subida = _get_subida_activa(conn)

    if modo == "minuto":
        if minutos <= 0:
            total = tarifa_minima
        else:
            total = tarifa_minima + (max(minutos - 1, 0) * valor_minuto)

        if subida:
            minutos_extra = _calcular_minutos_en_subida(
                fecha_ingreso,
                fecha_salida,
                subida["hora_inicio"],
                subida["hora_fin"],
            )
            if minutos_extra > 0:
                total += minutos_extra * int(subida["monto_adicional"])

        return minutos, round(total), "Modo minuto"

    if modo == "personalizado":
        tramos = _list_tarifas_personalizadas(conn)

        if subida:
            hora_inicio = datetime.combine(
                fecha_salida.date(),
                datetime.strptime(_time_as_hhmm(subida["hora_inicio"]), "%H:%M").time(),
            )
            hora_fin = datetime.combine(
                fecha_salida.date(),
                datetime.strptime(_time_as_hhmm(subida["hora_fin"]), "%H:%M").time(),
            )
            if hora_fin <= hora_inicio:
                hora_fin += timedelta(days=1)
            if hora_inicio <= fecha_salida <= hora_fin:
                tramos = [
                    {**tramo, "valor": tramo["valor"] + int(subida["monto_adicional"])}
                    for tramo in tramos
                ]

        if not tramos:
            return minutos, tarifa_minima, "Modo personalizado sin tramos"

        ultimo_tramo = tramos[-1]
        duracion_ciclo = ultimo_tramo["minuto_fin"] + 1
        horas_completas = minutos // duracion_ciclo
        minutos_restantes = minutos % duracion_ciclo
        total = horas_completas * ultimo_tramo["valor"]

        for tramo in tramos:
            if tramo["minuto_inicio"] <= minutos_restantes <= tramo["minuto_fin"]:
                total += tramo["valor"]
                break
        else:
            total += ultimo_tramo["valor"]

        return minutos, round(total), "Modo personalizado"

    if modo == "auto":
        bloques = (minutos // 60) + (1 if minutos % 60 > 0 else 0)
        total = tarifa_minima + (max(bloques - 1, 0) * tarifa_minima)

        if subida:
            minutos_extra = _calcular_minutos_en_subida(
                fecha_ingreso,
                fecha_salida,
                subida["hora_inicio"],
                subida["hora_fin"],
            )
            if minutos_extra > 0:
                total += (minutos_extra // 5) * int(subida["monto_adicional"])

        return minutos, round(total), "Modo auto"

    # Compatibilidad: versiones tempranas de la API usaban "tarifa_por_hora",
    # pero el escritorio y schema canónico usan "tarifa_hora".
    tarifa_hora = _get_config_int(conn, "tarifa_por_hora", 0)
    if tarifa_hora <= 0:
        tarifa_hora = _get_config_int(conn, "tarifa_hora", 600)

    if minutos <= 60:
        return minutos, tarifa_minima, "MVP: tarifa mínima (<= 60 min)"

    extra_horas = int(math.ceil((minutos - 60) / 60.0))
    monto = tarifa_minima + extra_horas * tarifa_hora
    return minutos, monto, f"MVP: mínima + {extra_horas}h extra"
