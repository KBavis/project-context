from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import List, Optional

class Settings(BaseSettings):

    PROJECT_NAME: str = "Project Context"
    PYTHONDONTWRITEBYTECODE: int = 1
    DB_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / '.env',
        env_file_encoding="utf-8"
    )


settings = Settings()

    