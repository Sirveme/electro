"""
app/config.py

Configuración centralizada del proyecto electro.
Carga variables de entorno desde .env (local) o desde el entorno (Railway).

Uso:
    from app.config import settings
    print(settings.DATABASE_URL)
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuración de la aplicación.

    Todas las variables se leen automáticamente de:
    1. Variables de entorno del sistema (Railway, sistema operativo)
    2. Archivo .env en la raíz del proyecto (solo en desarrollo local)

    El orden de prioridad es: entorno > .env > valor por defecto.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # ignora variables extra en .env sin romper
    )

    # ---------------------------------------------------------------------
    # Base de datos
    # ---------------------------------------------------------------------
    # Railway entrega DATABASE_URL con prefijo 'postgresql://' que es sync.
    # SQLAlchemy async necesita 'postgresql+asyncpg://'.
    # El validator de abajo hace la transformación automáticamente.
    DATABASE_URL: str

    # URL síncrona para scripts CLI (psycopg2). Si no se provee, se deriva del async.
    DATABASE_URL_SYNC: str = ""

    # ---------------------------------------------------------------------
    # Sesiones / seguridad
    # ---------------------------------------------------------------------
    SECRET_KEY: str
    SESSION_MAX_AGE_SECONDS: int = 28800  # 8 horas por defecto

    # ---------------------------------------------------------------------
    # Entorno
    # ---------------------------------------------------------------------
    ENVIRONMENT: str = "development"  # development | production

    # =====================================================================
    # VALIDATORS
    # =====================================================================

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def force_asyncpg_driver(cls, v: str) -> str:
        """
        Transforma la URL de PostgreSQL para usar el driver async (asyncpg).

        Railway y muchos PaaS entregan la URL como 'postgresql://...'
        SQLAlchemy con create_async_engine() exige 'postgresql+asyncpg://...'
        """
        if v.startswith("postgresql+asyncpg://"):
            return v
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v.startswith("postgres://"):
            # Alias antiguo que aún usan algunos PaaS (Heroku histórico, etc.)
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        # Si llega con otro prefijo (sqlite, mysql, etc.) se deja pasar tal cual.
        return v

    @field_validator("DATABASE_URL_SYNC", mode="after")
    @classmethod
    def derive_sync_url(cls, v: str, info) -> str:
        """
        Si DATABASE_URL_SYNC no fue provista explícitamente, la derivamos
        de DATABASE_URL quitando el '+asyncpg'.

        Esto evita tener que setear dos variables en Railway: con una basta.
        """
        if v:
            # Si vino explícita, asegurar que NO tenga +asyncpg
            return v.replace("postgresql+asyncpg://", "postgresql://", 1)

        async_url = info.data.get("DATABASE_URL", "")
        if async_url.startswith("postgresql+asyncpg://"):
            return async_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return async_url

    @field_validator("SECRET_KEY", mode="after")
    @classmethod
    def secret_key_min_length(cls, v: str) -> str:
        """SECRET_KEY debe ser razonablemente larga."""
        if len(v) < 16:
            raise ValueError(
                "SECRET_KEY debe tener al menos 16 caracteres. "
                "Genera una con: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return v

    # =====================================================================
    # HELPERS
    # =====================================================================

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() in ("development", "dev", "local")


# Instancia única que se importa en toda la app
settings = Settings()