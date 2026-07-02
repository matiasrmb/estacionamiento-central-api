from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from app.db.database import db_conn
from app.repositories.accounting_contracts import build_accounting_summary


def build_cierre_summary_from_rows(
    parking_movements,
    bathroom_uses,
    wash_only_operations,
    fecha_cierre: datetime,
) -> Dict[str, Any]:
    summary = build_accounting_summary(parking_movements, bathroom_uses, wash_only_operations)
    dates = [row["fecha_hora_ingreso"] for row in parking_movements if row.get("fecha_hora_ingreso")]
    dates.extend(row["fecha_hora_fin"] for row in wash_only_operations if row.get("fecha_hora_fin"))
    fecha_inicio = min(dates) if dates else None

    return {
        "hay_pendiente": bool(parking_movements or bathroom_uses or wash_only_operations),
        "fecha_inicio": fecha_inicio,
        "fecha_cierre": fecha_cierre,
        **summary,
        "ids_ingresos": [int(row["id_ingreso"]) for row in parking_movements if row.get("id_ingreso")],
        "ids_operaciones_servicio": [
            int(row["id_operacion_servicio"])
            for row in wash_only_operations
            if row.get("id_operacion_servicio")
        ],
    }


def _build_pending_summary(conn) -> Dict[str, Any]:
    registros = conn.execute(
        text("""
            SELECT id_ingreso, fecha_hora_ingreso, fecha_hora_salida, tarifa_aplicada
            FROM ingresos
            WHERE fecha_hora_salida IS NOT NULL
              AND cerrado = FALSE
            ORDER BY fecha_hora_salida ASC
        """)
    ).mappings().all()

    fecha_cierre = datetime.now()
    lavados_solos = conn.execute(
        text("""
            SELECT id_operacion_servicio, fecha_hora_fin, estado, valor_lavado_snapshot
            FROM operaciones_servicio
            WHERE estado = 'FINALIZADO_COBRADO'
              AND COALESCE(cerrado, FALSE) = FALSE
              AND fecha_hora_fin IS NOT NULL
            ORDER BY fecha_hora_fin ASC
        """)
    ).mappings().all()

    if not registros and not lavados_solos:
        return {
            "hay_pendiente": False,
            "fecha_inicio": None,
            "fecha_cierre": None,
            "total_recaudado": 0,
            "total_ingresos": 0,
            "total_salidas": 0,
            "total_banos": 0,
            "total_banos_monto": 0,
            "total_lavados_solos": 0,
            "total_lavados_solos_monto": 0,
            "total_general": 0,
            "ids_ingresos": [],
            "ids_operaciones_servicio": [],
        }

    fechas_inicio = [row["fecha_hora_ingreso"] for row in registros]
    fechas_inicio.extend(row["fecha_hora_fin"] for row in lavados_solos)
    fecha_inicio = min(fechas_inicio)

    banos = conn.execute(
        text("""
            SELECT COUNT(*) AS cantidad, COALESCE(SUM(monto), 0) AS total
            FROM usos_bano
            WHERE fecha_hora BETWEEN :fecha_inicio AND :fecha_cierre
        """),
        {"fecha_inicio": fecha_inicio, "fecha_cierre": fecha_cierre},
    ).mappings().first()

    total_banos = int((banos or {}).get("cantidad") or 0)
    bathroom_uses = [{"monto": int((banos or {}).get("total") or 0)}] if total_banos else []
    summary = build_cierre_summary_from_rows(registros, bathroom_uses, lavados_solos, fecha_cierre)
    summary["fecha_inicio"] = fecha_inicio
    summary["total_banos"] = total_banos

    return summary


def get_cierre_pendiente() -> Dict[str, Any]:
    with db_conn() as conn:
        summary = _build_pending_summary(conn)
    return _serialize_summary(summary)


def realizar_cierre(usuario: str) -> Dict[str, Any]:
    with db_conn() as conn:
        summary = _build_pending_summary(conn)
        if not summary["hay_pendiente"]:
            raise LookupError("NO_PENDING_CLOSURE")

        conn.execute(
            text("""
                INSERT INTO cierres_diarios (
                    fecha_inicio, fecha_cierre, total_recaudado,
                    total_ingresos, total_salidas, total_banos,
                    total_banos_monto, total_lavados_solos,
                    total_lavados_solos_monto, total_general, usuario
                )
                VALUES (
                    :fecha_inicio, :fecha_cierre, :total_recaudado,
                    :total_ingresos, :total_salidas, :total_banos,
                    :total_banos_monto, :total_lavados_solos,
                    :total_lavados_solos_monto, :total_general, :usuario
                )
            """),
            {
                **summary,
                "usuario": usuario,
            },
        )

        conn.execute(
            text("""
                UPDATE ingresos
                SET cerrado = TRUE
                WHERE fecha_hora_salida IS NOT NULL
                  AND cerrado = FALSE
                  AND fecha_hora_salida <= :fecha_cierre
            """),
            {"fecha_cierre": summary["fecha_cierre"]},
        )
        conn.execute(
            text("""
                UPDATE operaciones_servicio
                SET cerrado = TRUE
                WHERE estado = 'FINALIZADO_COBRADO'
                  AND COALESCE(cerrado, FALSE) = FALSE
                  AND fecha_hora_fin <= :fecha_cierre
            """),
            {"fecha_cierre": summary["fecha_cierre"]},
        )
        conn.commit()

    serialized = _serialize_summary(summary)
    serialized["usuario"] = usuario
    return serialized


def list_cierres(limit: int = 20) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT id_cierre, fecha_inicio, fecha_cierre, total_recaudado,
                       total_ingresos, total_salidas, total_banos,
                       total_banos_monto, total_lavados_solos,
                       total_lavados_solos_monto, total_general, usuario
                FROM cierres_diarios
                ORDER BY fecha_cierre DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()

    items = []
    for row in rows:
        item = dict(row)
        item["fecha_inicio"] = _iso(item.get("fecha_inicio"))
        item["fecha_cierre"] = _iso(item.get("fecha_cierre"))
        item["total_recaudado"] = int(item.get("total_recaudado") or 0)
        item["total_banos_monto"] = int(item.get("total_banos_monto") or 0)
        item["total_lavados_solos"] = int(item.get("total_lavados_solos") or 0)
        item["total_lavados_solos_monto"] = int(item.get("total_lavados_solos_monto") or 0)
        item["total_general"] = int(item.get("total_general") or 0)
        items.append(item)
    return items


def _serialize_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(summary)
    data.pop("ids_ingresos", None)
    data["fecha_inicio"] = _iso(data.get("fecha_inicio"))
    data["fecha_cierre"] = _iso(data.get("fecha_cierre"))
    return data


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
