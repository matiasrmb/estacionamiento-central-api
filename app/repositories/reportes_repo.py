from datetime import date
from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn
from app.repositories.accounting_contracts import build_report_totals


def obtener_reporte(fecha_inicio: date, fecha_fin: date, patente: str = "") -> Dict[str, Any]:
    patente = patente.strip().upper()
    query = """
        SELECT
            v.patente,
            i.fecha_hora_ingreso,
            i.fecha_hora_salida,
            TIMESTAMPDIFF(MINUTE, i.fecha_hora_ingreso, i.fecha_hora_salida) AS minutos,
            i.tarifa_aplicada
        FROM ingresos i
        JOIN vehiculos v ON i.id_vehiculo = v.id_vehiculo
        WHERE i.fecha_hora_salida IS NOT NULL
          AND DATE(i.fecha_hora_salida) BETWEEN :fecha_inicio AND :fecha_fin
    """
    params: Dict[str, Any] = {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin}

    if patente:
        query += " AND v.patente = :patente"
        params["patente"] = patente

    query += " ORDER BY i.fecha_hora_salida ASC"

    with db_conn() as conn:
        rows = conn.execute(text(query), params).mappings().all()
        items = [_serialize_movimiento(row) for row in rows]

        accounting_items = list(items)
        lavados_solos = []
        pagos_mensuales = []
        cobros_noches = []
        if not patente:
            banos = conn.execute(
                text("""
                    SELECT fecha_hora, monto, usuario
                    FROM usos_bano
                    WHERE DATE(fecha_hora) BETWEEN :fecha_inicio AND :fecha_fin
                    ORDER BY fecha_hora ASC
                """),
                params,
            ).mappings().all()
            for bano in banos:
                items.append(
                    {
                        "tipo": "bano",
                        "patente": "[BAÑO]",
                        "fecha_hora_ingreso": _iso(bano["fecha_hora"]),
                        "fecha_hora_salida": _iso(bano["fecha_hora"]),
                        "minutos": 0,
                        "tarifa_aplicada": int(bano["monto"] or 0),
                        "usuario": bano.get("usuario"),
                    }
                )
            lavados_solos = conn.execute(
                text("""
                    SELECT patente, fecha_hora_inicio, fecha_hora_fin,
                           TIMESTAMPDIFF(MINUTE, fecha_hora_inicio, fecha_hora_fin) AS minutos,
                           valor_lavado_snapshot, estado, usuario_fin
                    FROM operaciones_servicio
                    WHERE estado = 'FINALIZADO_COBRADO'
                      AND fecha_hora_fin IS NOT NULL
                      AND DATE(fecha_hora_fin) BETWEEN :fecha_inicio AND :fecha_fin
                    ORDER BY fecha_hora_fin ASC
                """),
                params,
            ).mappings().all()
            for lavado in lavados_solos:
                items.append(_serialize_solo_lavado(lavado))
        monthly_payments_query = """
            SELECT v.patente, p.fecha_pago, p.monto_snapshot, p.usuario,
                   p.metodo_pago, p.observacion, p.periodo
            FROM pagos_mensuales p
            JOIN vehiculos v ON v.id_vehiculo = p.id_vehiculo
            WHERE DATE(p.fecha_pago) BETWEEN :fecha_inicio AND :fecha_fin
        """
        if patente:
            monthly_payments_query += " AND v.patente = :patente"
        monthly_payments_query += " ORDER BY p.fecha_pago ASC"
        pagos_mensuales = conn.execute(
            text(monthly_payments_query),
            params,
        ).mappings().all()
        for pago in pagos_mensuales:
            items.append(_serialize_pago_mensual(pago))
        night_charges_query = """
            SELECT v.patente, c.fecha_hora_pago, c.monto_snapshot, c.usuario,
                   c.hora_inicio_snapshot, c.hora_fin_snapshot
            FROM cobros_noches c
            JOIN ingresos i ON i.id_ingreso = c.id_ingreso
            JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
            WHERE c.estado = 'PAGADO'
              AND DATE(c.fecha_hora_pago) BETWEEN :fecha_inicio AND :fecha_fin
        """
        if patente:
            night_charges_query += " AND v.patente = :patente"
        night_charges_query += " ORDER BY c.fecha_hora_pago ASC, c.id_cobro_noche ASC"
        cobros_noches = conn.execute(text(night_charges_query), params).mappings().all()
        for cobro in cobros_noches:
            items.append(_serialize_cobro_noche(cobro))

    items.sort(key=lambda item: item["fecha_hora_salida"] or "")
    totals = build_report_totals(accounting_items, lavados_solos, pagos_mensuales, cobros_noches)
    totals["total_movimientos"] = len(items)
    return {
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
        "patente": patente,
        "items": items,
        **totals,
    }


def _serialize_movimiento(row) -> Dict[str, Any]:
    return {
        "tipo": "vehiculo",
        "patente": row["patente"],
        "fecha_hora_ingreso": _iso(row["fecha_hora_ingreso"]),
        "fecha_hora_salida": _iso(row["fecha_hora_salida"]),
        "minutos": int(row["minutos"] or 0),
        "tarifa_aplicada": int(row["tarifa_aplicada"] or 0),
    }


def _serialize_solo_lavado(row) -> Dict[str, Any]:
    return {
        "tipo": "lavado_solo",
        "patente": row["patente"],
        "fecha_hora_ingreso": _iso(row["fecha_hora_inicio"]),
        "fecha_hora_salida": _iso(row["fecha_hora_fin"]),
        "minutos": int(row["minutos"] or 0),
        "tarifa_aplicada": int(row["valor_lavado_snapshot"] or 0),
        "usuario": row.get("usuario_fin"),
    }


def _serialize_pago_mensual(row) -> Dict[str, Any]:
    return {
        "tipo": "pago_mensual",
        "patente": row["patente"],
        "fecha_hora_ingreso": _iso(row["fecha_pago"]),
        "fecha_hora_salida": _iso(row["fecha_pago"]),
        "minutos": 0,
        "tarifa_aplicada": int(row["monto_snapshot"] or 0),
        "usuario": row.get("usuario"),
        "metodo_pago": row.get("metodo_pago"),
        "observacion": row.get("observacion"),
        "periodo": _iso(row.get("periodo")),
    }


def _serialize_cobro_noche(row) -> Dict[str, Any]:
    return {
        "tipo": "noche",
        "patente": row["patente"],
        "fecha_hora_ingreso": _iso(row["fecha_hora_pago"]),
        "fecha_hora_salida": _iso(row["fecha_hora_pago"]),
        "minutos": 0,
        "tarifa_aplicada": int(row["monto_snapshot"] or 0),
        "usuario": row.get("usuario"),
        "hora_inicio_snapshot": _iso(row.get("hora_inicio_snapshot")),
        "hora_fin_snapshot": _iso(row.get("hora_fin_snapshot")),
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
