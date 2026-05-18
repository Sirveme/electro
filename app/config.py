from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/electro"
    DATABASE_URL_SYNC: str = "postgresql://user:pass@localhost:5432/electro"
    SECRET_KEY: str = "cambiar-en-produccion-32-caracteres-min"
    SESSION_MAX_AGE_SECONDS: int = 28800
    ENVIRONMENT: str = "development"

    OPENAI_API_KEY: str = ""
    GCS_BUCKET_NAME: str = ""
    GCS_PROJECT_ID: str = ""
    GCS_SERVICE_ACCOUNT_JSON: str = ""


settings = Settings()
