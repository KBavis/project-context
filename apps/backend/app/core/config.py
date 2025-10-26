from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):

    PROJECT_NAME: str = "Project Context"
    PYTHONDONTWRITEBYTECODE: int = 1
    REL_DB_URL: str = ""
    VECTOR_DB_HOST: str = "localhost"
    VECTOR_DB_PORT: int = 8000

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / '.env',
        env_file_encoding="utf-8"
    )


settings = Settings()

    