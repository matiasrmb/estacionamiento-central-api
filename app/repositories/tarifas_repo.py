from typing import List, Dict, Any
from sqlalchemy import text
from app.db.database import db_conn


def list_tarifas_personalizadas() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            text("SELECT minuto_inicio, minuto_fin, valor FROM tarifas_personalizadas ORDER BY minuto_inicio ASC")
        ).mappings().all()
    return [dict(r) for r in rows]