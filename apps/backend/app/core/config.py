from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional, Set

class Settings(BaseSettings):

    PROJECT_NAME: str = "Project Context"
    PYTHONDONTWRITEBYTECODE: int = 1
    REL_DB_URL: str = ""
    VECTOR_DB_HOST: str = "localhost"
    VECTOR_DB_PORT: int = 8000

    DOCS_EMBEDDING_PROVIDER: str = "HuggingFace"
    DOCS_EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"

    CODE_EMBEDDING_PROVIDER: Optional[str] = "HuggingFace"
    CODE_EMBEDDING_MODEL: Optional[str] = "jinaai/ina-embeddings-v2-base-code"

    GITHUB_SECRET_TOKEN: Optional[str] = None
    HUGGING_FACE_API_KEY: Optional[str] = None
    OPEN_AI_API_KEY: Optional[str] = None

    VALID_PROIVDERS: list = ["OpenAI", "HuggingFace"] 

    CODE_FILE_EXTENSIONS: Set[str] = {
        'c', 
        'cpp',
        'cs',
        'java',
        'js',
        'py',
        'php',
        'html',
        'css',
        'swift',
        'rb',
        'pl',
        'sh',
        'sql',
        'xml',
        'json',
        'md',
        'yaml',
        'yml'
    }

    DOCS_FILE_EXTENSIONS: Set[str] = {
        'doc',
        'docx', 
        'pdf', 
        'txt' 
    }

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / '.env',
        env_file_encoding="utf-8"
    )

    


settings = Settings()

    