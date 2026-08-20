from datetime import datetime
from typing import Any, Dict


def build_ticket_ingreso_payload(
    id_ingreso: int,
    patente: str,
    hora_ingreso_iso: str,
    usuario_claims: Dict[str, Any],
    server_time_iso: str,
    cobro_noche: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = {
        "kind": "TICKET_INGRESO",
        "id_ingreso": id_ingreso,
        "patente": patente,
        "hora_ingreso": hora_ingreso_iso,
        "usuario": {
            "id_usuario": usuario_claims.get("id_usuario"),
            "usuario": usuario_claims.get("sub"),
            "rol": usuario_claims.get("rol"),
        },
        "tarifa": {
            "monto_preliminar": 0,
        },
        "meta": {"server_time": server_time_iso, "version": 1},
    }
    if cobro_noche:
        payload["noches"] = cobro_noche
    return payload
