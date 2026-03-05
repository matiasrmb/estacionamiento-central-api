from pydantic_settings import BaseSettings, SettingsConfigDict


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
    db_user: str = "root"
    db_password: str = "4Da46151-"
    db_name: str = "estacionamiento_db"

    # Pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800

    # JWT
    jwt_secret: str = "CHANGE_ME"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 720


settings = Settings()