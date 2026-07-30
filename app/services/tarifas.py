import math
from datetime import datetime, timedelta
from sqlalchemy import bindparam, text
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


def _config_int(config: dict[str, str], clave: str, default: int) -> int:
    try:
        return int(float(config.get(clave, default)))
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


def _cargar_contexto_tarifas(conn: Connection) -> tuple[dict[str, str], dict[str, object] | None, list[dict[str, int]]]:
    config = _get_config(conn)
    subida = _get_subida_activa(conn)
    tramos = _list_tarifas_personalizadas(conn) if config.get("modo_cobro", "minuto") == "personalizado" else []
    return config, subida, tramos


def _time_as_hhmm(value: object) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]


def _calcular_minutos_completos(segundos: float) -> int:
    """Convierte una duración a minutos completos, igual que Desktop."""
    return max(0, int(segundos / 60))


def calcular_minutos_fuera_modo_noche(
    fecha_hora_ingreso: datetime,
    fecha_hora_salida: datetime,
) -> dict[str, int]:
    """Calcula extras fuera de la gracia fija del modo Noche: 19:00 a 10:00."""
    if fecha_hora_salida <= fecha_hora_ingreso:
        return {"antes": 0, "despues": 0, "total": 0}
    fecha_noche = fecha_hora_ingreso.date()
    if fecha_hora_ingreso.time() <= datetime.strptime("10:00", "%H:%M").time():
        fecha_noche -= timedelta(days=1)
    inicio_gracia = datetime.combine(fecha_noche, datetime.strptime("19:00", "%H:%M").time())
    fin_gracia = inicio_gracia + timedelta(hours=15)
    antes = _calcular_minutos_completos((min(inicio_gracia, fecha_hora_salida) - fecha_hora_ingreso).total_seconds())
    despues = _calcular_minutos_completos((fecha_hora_salida - max(fin_gracia, fecha_hora_ingreso)).total_seconds())
    return {"antes": antes, "despues": despues, "total": antes + despues}


def calcular_intervalos_fuera_modo_noche(
    fecha_hora_ingreso: datetime,
    fecha_hora_salida: datetime,
) -> list[tuple[datetime, datetime]]:
    """Retorna los tramos cobrables fuera de la gracia fija 19:00-10:00."""
    if fecha_hora_salida <= fecha_hora_ingreso:
        return []

    fecha_noche = fecha_hora_ingreso.date()
    if fecha_hora_ingreso.time() <= datetime.strptime("10:00", "%H:%M").time():
        fecha_noche -= timedelta(days=1)
    inicio_gracia = datetime.combine(fecha_noche, datetime.strptime("19:00", "%H:%M").time())
    fin_gracia = inicio_gracia + timedelta(hours=15)
    intervalos = []
    if fecha_hora_ingreso < inicio_gracia:
        intervalos.append((fecha_hora_ingreso, min(inicio_gracia, fecha_hora_salida)))
    if fecha_hora_salida > fin_gracia:
        intervalos.append((max(fin_gracia, fecha_hora_ingreso), fecha_hora_salida))
    return [(inicio, fin) for inicio, fin in intervalos if fin > inicio]


def _descontar_intervalos(
    intervalos: list[tuple[datetime, datetime]],
    descuentos: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Sustrae lavados sólo de los tramos cobrables."""
    restantes = list(intervalos)
    for descuento_inicio, descuento_fin in descuentos:
        nuevos = []
        for inicio, fin in restantes:
            solapamiento_inicio = max(inicio, descuento_inicio)
            solapamiento_fin = min(fin, descuento_fin)
            if solapamiento_inicio >= solapamiento_fin:
                nuevos.append((inicio, fin))
                continue
            if inicio < solapamiento_inicio:
                nuevos.append((inicio, solapamiento_inicio))
            if solapamiento_fin < fin:
                nuevos.append((solapamiento_fin, fin))
        restantes = nuevos
    return restantes


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


def _calcular_monto_desde_minutos_con_contexto(
    minutos: int,
    fecha_ingreso: datetime,
    fecha_salida: datetime,
    config: dict[str, str],
    subida: dict[str, object] | None,
    tramos: list[dict[str, int]],
) -> tuple[int, int, str]:
    """
    Retorna (minutos, monto, detalle) usando minutos ya ajustados.

    Replica la lógica principal del escritorio para mantener cobros consistentes:
    - modo minuto: tarifa mínima + valor por minuto adicional
    - modo personalizado: tramos cíclicos
    - modo auto: bloques por hora usando tarifa mínima
    - subida temporal: recargo según el modo
    """
    minutos = max(0, int(minutos))

    modo = config.get("modo_cobro", "minuto")
    tarifa_minima = int(config.get("tarifa_minima", 300))
    valor_minuto = int(config.get("valor_minuto", 25))

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

        tramo_aplicado = None
        for tramo in tramos:
            if tramo["minuto_inicio"] <= minutos_restantes <= tramo["minuto_fin"]:
                total += tramo["valor"]
                tramo_aplicado = tramo
                break
        else:
            total += ultimo_tramo["valor"]
            tramo_aplicado = ultimo_tramo

        detalle = "Modo personalizado"
        if tramo_aplicado:
            detalle = (
                f"Modo personalizado - tramo "
                f"{tramo_aplicado['minuto_inicio']}-{tramo_aplicado['minuto_fin']} min"
            )
            if horas_completas:
                detalle += f" (+{horas_completas} ciclo(s) completo(s))"

        return minutos, round(total), detalle

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
    tarifa_hora = _config_int(config, "tarifa_por_hora", 0)
    if tarifa_hora <= 0:
        tarifa_hora = _config_int(config, "tarifa_hora", 600)

    if minutos <= 60:
        return minutos, tarifa_minima, "MVP: tarifa mínima (<= 60 min)"

    extra_horas = int(math.ceil((minutos - 60) / 60.0))
    monto = tarifa_minima + extra_horas * tarifa_hora
    return minutos, monto, f"MVP: mínima + {extra_horas}h extra"


def calcular_monto_desde_minutos(
    conn: Connection,
    minutos: int,
    fecha_ingreso: datetime,
    fecha_salida: datetime,
) -> tuple[int, int, str]:
    """Calcula una tarifa con la configuración vigente."""
    config, subida, tramos = _cargar_contexto_tarifas(conn)
    return _calcular_monto_desde_minutos_con_contexto(
        minutos, fecha_ingreso, fecha_salida, config, subida, tramos
    )


def _calcular_monto_por_intervalos_con_contexto(
    intervalos: list[tuple[datetime, datetime]],
    config: dict[str, str],
    subida: dict[str, object] | None,
    tramos: list[dict[str, int]],
) -> tuple[int, int, str]:
    """Suma tarifas de tramos cobrables sin exponer recargos al tiempo de gracia."""
    minutos = 0
    monto = 0
    detalles = []
    for inicio, fin in intervalos:
        minutos_intervalo, monto_intervalo, detalle = _calcular_monto_desde_minutos_con_contexto(
            _calcular_minutos_completos((fin - inicio).total_seconds()),
            inicio,
            fin,
            config,
            subida,
            tramos,
        )
        minutos += minutos_intervalo
        monto += monto_intervalo
        detalles.append(detalle)
    return minutos, monto, detalles[0] if len(set(detalles)) == 1 else "Tarifa por intervalos"


def calcular_monto_mvp(conn: Connection, fecha_ingreso: datetime, fecha_salida: datetime) -> tuple[int, int, str]:
    """
    Retorna (minutos, monto, detalle) calculando minutos desde las fechas reales.
    """
    diff = (fecha_salida - fecha_ingreso).total_seconds()
    minutos = _calcular_minutos_completos(diff)
    return calcular_monto_desde_minutos(conn, minutos, fecha_ingreso, fecha_salida)


def _calcular_minutos_lavado(conn: Connection, id_ingreso: int, fecha_salida: datetime) -> int:
    return sum(
        _calcular_minutos_completos((fin - inicio).total_seconds())
        for inicio, fin in _obtener_intervalos_lavado(conn, id_ingreso, fecha_salida)
    )


def _obtener_intervalos_lavado(
    conn: Connection, id_ingreso: int, fecha_salida: datetime
) -> list[tuple[datetime, datetime]]:
    rows = conn.execute(
        text("""
            SELECT fecha_hora_inicio, fecha_hora_fin
            FROM lavados
            WHERE id_ingreso = :id_ingreso
        """),
        {"id_ingreso": id_ingreso},
    ).mappings().all()

    intervalos = []
    for row in rows:
        inicio = row["fecha_hora_inicio"]
        fin = min(row["fecha_hora_fin"] or fecha_salida, fecha_salida)
        if fin > inicio:
            intervalos.append((inicio, fin))
    return intervalos


def _calcular_total_lavados(conn: Connection, id_ingreso: int) -> int:
    total = conn.execute(
        text("""
            SELECT COALESCE(SUM(valor_lavado), 0)
            FROM lavados
            WHERE id_ingreso = :id_ingreso
        """),
        {"id_ingreso": id_ingreso},
    ).scalar()
    return int(total or 0)


def _calcular_total_lavados_convertidos(conn: Connection, id_ingreso: int) -> int:
    total = conn.execute(
        text("""
            SELECT COALESCE(SUM(valor_lavado_snapshot), 0)
            FROM operaciones_servicio
            WHERE id_ingreso_generado = :id_ingreso
              AND estado = 'CONVERTIDO_ESTADIA'
        """),
        {"id_ingreso": id_ingreso},
    ).scalar()
    return int(total or 0)


def calcular_monto_con_lavados(
    conn: Connection,
    id_ingreso: int,
    fecha_ingreso: datetime,
    fecha_salida: datetime,
    modo_noche: bool = False,
) -> tuple[int, int, str, int, int]:
    """Calcula la cotización de estadía con los mismos ajustes que una salida."""
    minutos_totales = _calcular_minutos_completos(
        (fecha_salida - fecha_ingreso).total_seconds()
    )
    minutos_noche = calcular_minutos_fuera_modo_noche(fecha_ingreso, fecha_salida) if modo_noche else None
    intervalos_cobrables = []
    if modo_noche:
        intervalos_cobrables = _descontar_intervalos(
            calcular_intervalos_fuera_modo_noche(fecha_ingreso, fecha_salida),
            _obtener_intervalos_lavado(conn, id_ingreso, fecha_salida),
        )
        minutos_cobrables = sum(
            _calcular_minutos_completos((fin - inicio).total_seconds())
            for inicio, fin in intervalos_cobrables
        )
    else:
        minutos_lavado = _calcular_minutos_lavado(conn, id_ingreso, fecha_salida)
        minutos_cobrables = max(minutos_totales - minutos_lavado, 0)
    total_lavados = _calcular_total_lavados(conn, id_ingreso)
    total_lavados_convertidos = _calcular_total_lavados_convertidos(conn, id_ingreso)
    total_lavados += total_lavados_convertidos

    if modo_noche and minutos_cobrables == 0:
        minutos, monto_estacionamiento, detalle = 0, 0, "Modo Noche sin extra de estacionamiento"
    elif modo_noche:
        config, subida, tramos = _cargar_contexto_tarifas(conn)
        minutos, monto_estacionamiento, detalle = _calcular_monto_por_intervalos_con_contexto(
            intervalos_cobrables, config, subida, tramos
        )
    else:
        minutos, monto_estacionamiento, detalle = calcular_monto_desde_minutos(
            conn,
            minutos_cobrables,
            fecha_ingreso,
            fecha_salida,
        )
    if minutos_noche:
        detalle = f"{detalle} - extra modo Noche: {minutos_noche['total']} min"
    monto_total = monto_estacionamiento + total_lavados
    if modo_noche:
        minutos_lavado = minutos_noche["total"] - minutos_cobrables
    if minutos_lavado > 0:
        detalle = f"{detalle} - descuenta {minutos_lavado} min de lavado"
    if total_lavados > 0:
        detalle = f"{detalle} - lavados ${total_lavados}"
    if total_lavados_convertidos > 0:
        detalle = f"{detalle} (incluye solo lavado convertido ${total_lavados_convertidos})"
    return minutos, monto_total, detalle, monto_estacionamiento, total_lavados


def calcular_montos_activos_con_lavados(
    conn: Connection,
    ingresos: list[dict[str, object]],
    calculado_a: datetime,
) -> dict[int, tuple[int, int, str, int, int]]:
    """Cotiza activos sin repetir consultas de lavados ni tarifas por ingreso."""
    if not ingresos:
        return {}

    ids = [int(ingreso["id_ingreso"]) for ingreso in ingresos]
    lavado_rows = conn.execute(
        text("""
            SELECT id_ingreso, fecha_hora_inicio, fecha_hora_fin
            FROM lavados
            WHERE id_ingreso IN :ids
        """).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).mappings().all()
    lavado_totales = conn.execute(
        text("""
            SELECT id_ingreso, COALESCE(SUM(valor_lavado), 0) AS total
            FROM lavados
            WHERE id_ingreso IN :ids
            GROUP BY id_ingreso
        """).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).mappings().all()
    convertidos_totales = conn.execute(
        text("""
            SELECT id_ingreso_generado, COALESCE(SUM(valor_lavado_snapshot), 0) AS total
            FROM operaciones_servicio
            WHERE id_ingreso_generado IN :ids
              AND estado = 'CONVERTIDO_ESTADIA'
            GROUP BY id_ingreso_generado
        """).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).mappings().all()

    intervalos_lavado = {id_ingreso: [] for id_ingreso in ids}
    for lavado in lavado_rows:
        inicio = lavado["fecha_hora_inicio"]
        fin = min(lavado["fecha_hora_fin"] or calculado_a, calculado_a)
        if fin > inicio:
            intervalos_lavado[int(lavado["id_ingreso"])].append((inicio, fin))

    total_lavados = {int(row["id_ingreso"]): int(row["total"] or 0) for row in lavado_totales}
    total_convertidos = {
        int(row["id_ingreso_generado"]): int(row["total"] or 0)
        for row in convertidos_totales
    }
    config, subida, tramos = _cargar_contexto_tarifas(conn)

    cotizaciones = {}
    for ingreso in ingresos:
        id_ingreso = int(ingreso["id_ingreso"])
        minutos_totales = _calcular_minutos_completos(
            (calculado_a - ingreso["fecha_hora_ingreso"]).total_seconds()
        )
        minutos_noche = calcular_minutos_fuera_modo_noche(ingreso["fecha_hora_ingreso"], calculado_a) if ingreso.get("modo_noche") else None
        intervalos_cobrables = []
        if minutos_noche:
            intervalos_cobrables = _descontar_intervalos(
                calcular_intervalos_fuera_modo_noche(ingreso["fecha_hora_ingreso"], calculado_a),
                intervalos_lavado[id_ingreso],
            )
            minutos_cobrables = sum(
                _calcular_minutos_completos((fin - inicio).total_seconds())
                for inicio, fin in intervalos_cobrables
            )
        else:
            minutos_cobrables = max(
                minutos_totales - sum(
                    _calcular_minutos_completos((fin - inicio).total_seconds())
                    for inicio, fin in intervalos_lavado[id_ingreso]
                ),
                0,
            )
        if minutos_noche and minutos_cobrables == 0:
            minutos, monto_estacionamiento, detalle = 0, 0, "Modo Noche sin extra de estacionamiento"
        elif minutos_noche:
            minutos, monto_estacionamiento, detalle = _calcular_monto_por_intervalos_con_contexto(
                intervalos_cobrables, config, subida, tramos
            )
        else:
            minutos, monto_estacionamiento, detalle = _calcular_monto_desde_minutos_con_contexto(
                minutos_cobrables,
                ingreso["fecha_hora_ingreso"],
                calculado_a,
                config,
                subida,
                tramos,
            )
        if minutos_noche:
            detalle = f"{detalle} - extra modo Noche: {minutos_noche['total']} min"
        total = total_lavados.get(id_ingreso, 0) + total_convertidos.get(id_ingreso, 0)
        minutos_lavado = (
            minutos_noche["total"] - minutos_cobrables
            if minutos_noche
            else minutos_totales - minutos_cobrables
        )
        if minutos_lavado > 0:
            detalle = f"{detalle} - descuenta {minutos_lavado} min de lavado"
        if total > 0:
            detalle = f"{detalle} - lavados ${total}"
        if total_convertidos.get(id_ingreso, 0) > 0:
            detalle = f"{detalle} (incluye solo lavado convertido ${total_convertidos[id_ingreso]})"
        cotizaciones[id_ingreso] = (minutos, monto_estacionamiento + total, detalle, monto_estacionamiento, total)
    return cotizaciones
