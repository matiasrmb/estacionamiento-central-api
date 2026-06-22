from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import require_role
from app.db.database import db_conn

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

        return {"items": [dict(r) for r in rows]}
