def cotizar_estadia(minutos, monto_estadia, tamano_vehiculo=None):
    return {
        "tipo": "estadia",
        "minutos": int(minutos),
        "monto": int(monto_estadia),
    }


def cotizar_lavado(tipo_lavado, monto_lavado):
    return {
        "tipo": "lavado",
        "tipo_lavado": tipo_lavado,
        "monto": int(monto_lavado),
    }


def cotizar_mensualidad(vehiculos):
    detalles = []
    total_mensual = 0
    total_diario = 0
    requiere_monto = False

    for vehiculo in vehiculos:
        monto = _resolver_monto_mensual(vehiculo)
        if monto is None:
            requiere_monto = True
            detalles.append({
                "patente": vehiculo.get("patente"),
                "monto_mensual": None,
                "costo_diario": None,
                "requiere_monto": True,
            })
            continue

        costo_diario = round(monto / 30)
        total_mensual += monto
        total_diario += costo_diario
        detalles.append({
            "patente": vehiculo.get("patente"),
            "monto_mensual": monto,
            "costo_diario": costo_diario,
            "requiere_monto": False,
        })

    return {
        "tipo": "mensualidad",
        "vehiculos": detalles,
        "total_mensual": total_mensual,
        "total_diario": total_diario,
        "requiere_monto": requiere_monto,
        "monto": total_mensual,
    }


def cotizar_combinada(*items):
    items_validos = [item for item in items if item]
    return {
        "tipo": "combinada",
        "items": items_validos,
        "total": sum(int(item.get("monto") or 0) for item in items_validos),
    }


def preview_cotizacion(payload):
    items = []

    estadia = payload.get("estadia") or {}
    if estadia:
        items.append(cotizar_estadia(
            estadia.get("minutos", 0),
            estadia.get("monto_estadia", 0),
            tamano_vehiculo=estadia.get("tamano_vehiculo"),
        ))

    lavado = payload.get("lavado") or {}
    if lavado:
        items.append(cotizar_lavado(
            lavado.get("tipo_lavado"),
            lavado.get("monto_lavado", 0),
        ))

    mensualidad = payload.get("mensualidad") or {}
    if mensualidad:
        preview_mensual = cotizar_mensualidad(mensualidad.get("vehiculos", []))
        if preview_mensual["requiere_monto"]:
            raise ValueError("MONTHLY_AMOUNT_REQUIRED")
        items.append(preview_mensual)

    preview = cotizar_combinada(*items)
    preview["creates_billable_rows"] = False
    return preview


def _resolver_monto_mensual(vehiculo):
    for clave in ("monto_mensual", "monto_configurado", "monto_mensual_default"):
        monto = vehiculo.get(clave)
        if monto not in (None, "", 0, "0"):
            return int(monto)
    return None
