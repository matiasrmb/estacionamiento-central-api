from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import require_role
from app.db.database import db_conn
from app.services.tarifas import calcular_montos_activos_con_lavados

router = APIRouter(tags=["activos"])


@router.get("/activos")
def listar_activos(_user=Depends(require_role("operador", "admin"))):
    """
    Activos = ingresos con fecha_hora_salida NULL.
    Devuelve lista en formato simple para Flutter.
    """
    with db_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT i.id_ingreso,
                       v.patente,
                       i.fecha_hora_ingreso,
                       i.en_espera,
                       i.en_lavado,
                       i.usuario
                FROM ingresos i
                JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
                WHERE i.fecha_hora_salida IS NULL
                ORDER BY i.fecha_hora_ingreso ASC
            """)
        ).mappings().all()

        calculado_a = datetime.now().replace(microsecond=0)
        cotizables = [dict(row) for row in rows if int(row.get("en_espera") or 0) != 1]
        cotizaciones = calcular_montos_activos_con_lavados(conn, cotizables, calculado_a)
        items = []
        for row in rows:
            item = dict(row)
            if int(item.get("en_espera") or 0) == 1:
                item.update({"monto_acumulado": 0, "minutos_cobrables": 0})
            else:
                minutos, monto, _detalle, _monto_estacionamiento, _total_lavados = cotizaciones[int(item["id_ingreso"])]
                item.update({"monto_acumulado": int(monto), "minutos_cobrables": int(minutos)})
            item["calculado_a"] = calculado_a.isoformat()
            items.append(item)

        return {"items": items}
