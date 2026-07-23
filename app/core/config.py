from pydantic_settings import BaseSettings, SettingsConfigDict


PRODUCTION_ENVS = {"prod", "production"}
JWT_SECRET_PLACEHOLDERS = {"", "CHANGE_ME"}
DB_PASSWORD_PLACEHOLDERS = {"", "ec_app_2026"}


class Settings(BaseSettings):
    """
    Configuración central del backend.

    Carga variables desde archivo .env y desde el entorno del sistema.
    """
    model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)

    app_name: str = "EstacionamientoCentralAPI"
    env: str = "dev"  # dev | prod
    log_level: str = "INFO"

    # DB (MySQL local)
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "estacionamiento_app"
    db_password: str = ""
    db_name: str = "estacionamiento_db"

    # Pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800

    # JWT
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 720

    def is_production(self) -> bool:
        return self.env.strip().lower() in PRODUCTION_ENVS

    def validate_runtime_safety(self) -> None:
        if not self.is_production():
            return

        errors = []
        if self.jwt_secret.strip() in JWT_SECRET_PLACEHOLDERS:
            errors.append("JWT_SECRET must be configured for production")
        if self.db_password.strip() in DB_PASSWORD_PLACEHOLDERS:
            errors.append("DB_PASSWORD must be configured for production")
        if self.db_user.strip().lower() == "root":
            errors.append("DB_USER must not be root in production")

        if errors:
            raise RuntimeError("; ".join(errors))


settings = Settings()
