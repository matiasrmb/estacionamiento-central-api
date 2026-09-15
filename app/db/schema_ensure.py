SOLO_LAVADO_SCHEMA_UNAVAILABLE_MESSAGE = (
    "Solo lavado no disponible: no se pudo actualizar la base de datos. "
    "Contacte soporte / actualice DB."
)

NO_SOLO_LAVADO_PRICE_CONFIG_MESSAGE = (
    "Solo lavado no tiene precios activos configurados. "
    "Configurá o activá un precio/tipo de lavado en Configuración para Solo lavado."
)


class SoloLavadoSchemaUnavailable(RuntimeError):
    """Raised when the required Solo lavado schema is unavailable."""


def raise_if_missing_solo_lavado_schema(exc: Exception) -> None:
    """Translate a missing canonical wash pricing table error without modifying the DB."""
    message = str(exc).casefold()
    if "tipos_vehiculo_lavado" in message and any(
        marker in message
        for marker in ("doesn't exist", "does not exist", "no such table", "undefined table")
    ):
        raise SoloLavadoSchemaUnavailable(SOLO_LAVADO_SCHEMA_UNAVAILABLE_MESSAGE) from exc
