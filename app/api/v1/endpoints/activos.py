from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import require_role
from app.db.database import db_conn
from app.services.tarifas import calcular_montos_activos_con_lavados

router = APIRouter(tags=["activos"])


def build_active_items(conn, calculado_a: datetime, as_of: datetime | None = None):
    rows = conn.execute(
        text("""
                SELECT i.id_ingreso,
                       v.patente,
                       i.fecha_hora_ingreso,
                       i.en_espera,
                       i.en_lavado,
                       i.usuario,
                        EXISTS (
                            SELECT 1 FROM cobros_noches cn
                            WHERE cn.id_ingreso = i.id_ingreso
                               AND cn.estado = 'PAGADO'
                               AND (:as_of IS NULL OR cn.fecha_hora_pago <= :as_of)
                               AND (
                                    cn.estado_operativo = 'PENDIENTE'
                                    OR (
                                        :as_of IS NOT NULL
                                        AND cn.fecha_hora_resolucion > :as_of
                                    )
                               )
                        ) AS modo_noche
                FROM ingresos i
                JOIN vehiculos v ON v.id_vehiculo = i.id_vehiculo
                 WHERE (
                     (:as_of IS NULL AND i.fecha_hora_salida IS NULL)
                     OR (
                         :as_of IS NOT NULL
                         AND i.fecha_hora_ingreso <= :as_of
                         AND (i.fecha_hora_salida IS NULL OR i.fecha_hora_salida > :as_of)
                     )
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM ingresos_eliminados ie
                     WHERE ie.id_ingreso_original = i.id_ingreso
                 )
                 ORDER BY i.fecha_hora_ingreso ASC
            """),
        {"as_of": as_of},
    ).mappings().all()

    cotizables = [dict(row) for row in rows if int(row.get("en_espera") or 0) != 1 and not int(row.get("modo_noche") or 0)]
    cotizaciones = calcular_montos_activos_con_lavados(conn, cotizables, calculado_a, as_of=as_of)
    items = []
    for row in rows:
        item = dict(row)
        if int(item.get("en_espera") or 0) == 1 or int(item.get("modo_noche") or 0):
            item.update({"monto_acumulado": 0, "minutos_cobrables": 0})
        else:
            minutos, monto, _detalle, _monto_estacionamiento, _total_lavados = cotizaciones[int(item["id_ingreso"])]
            item.update({"monto_acumulado": int(monto), "minutos_cobrables": int(minutos)})
        item["calculado_a"] = calculado_a.isoformat()
        items.append(item)
    return items


@router.get("/activos")
def listar_activos(_user=Depends(require_role("operador", "admin"))):
    """
    Activos = ingresos con fecha_hora_salida NULL.
    Devuelve lista en formato simple para Flutter.
    """
    with db_conn() as conn:
        calculado_a = datetime.now().replace(microsecond=0)
        items = build_active_items(conn, calculado_a)

    return {"items": items}
