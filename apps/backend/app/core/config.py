from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional

class Settings(BaseSettings):

    PROJECT_NAME: str = "Project Context"
    PYTHONDONTWRITEBYTECODE: int = 1
    REL_DB_URL: str = ""
    VECTOR_DB_HOST: str = "localhost"
    VECTOR_DB_PORT: int = 8000

    DOCS_EMBEDDING_PROVIDER: str = "HuggingFace"
    DOCS_EMBEDDING_API_KEY: str = "api-key"
    DOCS_EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"

    CODE_EMBEDDING_PROVIDER: Optional[str] = None
    CODE_EMBEDDING_API_KEY: Optional[str] = None
    CODE_EMBEDDING_MODEL: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / '.env',
        env_file_encoding="utf-8"
    )


settings = Settings()

    