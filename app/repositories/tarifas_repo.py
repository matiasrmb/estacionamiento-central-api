from typing import List, Dict, Any
from sqlalchemy import text
from app.db.database import db_conn


def list_tarifas_personalizadas() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            text("""
                SELECT id_tarifa, minuto_inicio, minuto_fin, valor
                FROM tarifas_personalizadas
                ORDER BY minuto_inicio ASC
            """)
        ).mappings().all()
    return [dict(r) for r in rows]


def _validate_interval(conn, minuto_inicio: int, minuto_fin: int, id_excluir: int | None = None) -> None:
    if minuto_inicio < 0 or minuto_fin < minuto_inicio:
        raise ValueError("INVALID_INTERVAL")

    query = """
        SELECT COUNT(*)
        FROM tarifas_personalizadas
        WHERE NOT (minuto_fin < :inicio OR minuto_inicio > :fin)
    """
    params: Dict[str, Any] = {"inicio": minuto_inicio, "fin": minuto_fin}
    if id_excluir is not None:
        query += " AND id_tarifa <> :id_excluir"
        params["id_excluir"] = id_excluir

    overlaps = conn.execute(text(query), params).scalar()
    if int(overlaps or 0) > 0:
        raise ValueError("INTERVAL_OVERLAP")


def create_tarifa_personalizada(minuto_inicio: int, minuto_fin: int, valor: int) -> int:
    with db_conn() as conn:
        _validate_interval(conn, minuto_inicio, minuto_fin)
        conn.execute(
            text("""
                INSERT INTO tarifas_personalizadas (minuto_inicio, minuto_fin, valor)
                VALUES (:inicio, :fin, :valor)
            """),
            {"inicio": minuto_inicio, "fin": minuto_fin, "valor": valor},
        )
        conn.commit()
        new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
        return int(new_id)


def update_tarifa_personalizada(id_tarifa: int, minuto_inicio: int, minuto_fin: int, valor: int) -> None:
    with db_conn() as conn:
        _validate_interval(conn, minuto_inicio, minuto_fin, id_excluir=id_tarifa)
        result = conn.execute(
            text("""
                UPDATE tarifas_personalizadas
                SET minuto_inicio = :inicio,
                    minuto_fin = :fin,
                    valor = :valor
                WHERE id_tarifa = :id_tarifa
            """),
            {"id_tarifa": id_tarifa, "inicio": minuto_inicio, "fin": minuto_fin, "valor": valor},
        )
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("TARIFA_NOT_FOUND")


def delete_tarifa_personalizada(id_tarifa: int) -> None:
    with db_conn() as conn:
        result = conn.execute(
            text("DELETE FROM tarifas_personalizadas WHERE id_tarifa = :id_tarifa"),
            {"id_tarifa": id_tarifa},
        )
        conn.commit()
        if result.rowcount != 1:
            raise LookupError("TARIFA_NOT_FOUND")
