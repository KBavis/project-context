from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional, Set, Dict
import logging
import sys

# TODO: There may be a better way to handle the excess configs we have here, maybe having "generic" settings VS "llm" settings

# TODO: Move constants to constants.py and leave configurable values in herer 

class Settings(BaseSettings):

    PROJECT_NAME: str = "Contextualized"

    PYTHONDONTWRITEBYTECODE: int = 1

    SYNC_REL_DB_URL: str = ""
    ASYNC_REL_DB_URL: str = ""

    VECTOR_DB_HOST: str = "localhost"
    VECTOR_DB_PORT: int = 8000

    OLLAMA_LOCAL_HOST_URL: str = "http://localhost:11434"
    OLLAMA_KV_CACHE_TYPE: str = "f16"
    LLM_EXPECTED_RESPONSE_SIZE: int = 500 

    LL_MODEL_PROVIDER: str = "Ollama"
    LL_MODEL: str = "gpt-oss:latest"

    DOCS_EMBEDDING_PROVIDER: str = "HuggingFace"
    DOCS_EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"

    CODE_EMBEDDING_PROVIDER: Optional[str] = "HuggingFace"
    CODE_EMBEDDING_MODEL: Optional[str] = "microsoft/codebert-base"

    CROSS_ENCODING_MODEL: Optional[str] = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    GITHUB_SECRET_TOKEN: Optional[str] = None
    HUGGING_FACE_API_KEY: Optional[str] = None
    OPEN_AI_API_KEY: Optional[str] = None

    VALID_MODEL_PROIVDERS: list = ["OpenAI", "HuggingFace"]

    TMP: Optional[str] = "tmp"
    PROCESSED_DIR: Optional[str] = "/processed"
    TMP_DOCS: Optional[str] = f"{TMP}/docs"
    TMP_CODE: Optional[str] = f"{TMP}/code"

    ENV: Optional[str] = "dev"

    DOCLING_ACCELERATOR_DEVICE: Optional[str] = "cpu"

    VALID_DATA_PROVIDERS: Set[str] = {"GitHub", "BitBucket", "Confluence"}

    CODE_FILE_EXTENSIONS: Set[str] = {
        "c",
        "cpp",
        "cs",
        "java",
        "js",
        "jsx",
        "ts",
        "tsx",
        "py",
        "php",
        "html",
        "css",
        "swift",
        "rb",
        "pl",
        "sh",
        "sql",
        "xml",
        "json",
        "yaml",
        "yml",
    }

    EXTENSION_TO_LANGUAGE: Dict[str, str] = {
        "py": "python",
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "java": "java",
        "c": "c",
        "cpp": "cpp",
        "cs": "csharp",
        "rb": "ruby",
        "php": "php",
        "swift": "swift",
        "pl": "perl",
        "sh": "bash",
        "sql": "sql",
        "html": "html",
        "css": "css",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "xml": "xml",
    }

    DOCS_FILE_EXTENSIONS: Set[str] = {"docx", "pdf", "md"}

    model_config = SettingsConfigDict(
        extra='ignore',
        env_file=Path(__file__).resolve().parents[2] / ".env", env_file_encoding="utf-8"
    )


settings = Settings()

_LEVEL_BY_ENV: dict = {"prod": logging.INFO, "dev": logging.DEBUG}


def setup_logging():
    """
    Configure root logger
    """

    root = logging.getLogger()

    root.handlers.clear()  # clear existing handlers

    env = settings.ENV.lower() if hasattr(settings, "ENV") else "prod"
    level = _LEVEL_BY_ENV.get(env, logging.INFO)

    formatter = logging.Formatter(
        fmt="[%(asctime)s - %(name)s - %(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root.setLevel(level)
    root.addHandler(handler)

    # quiet noisy loggers
    for noisy in [
        "urllib3.connectionpool",
        "watchfiles.main",
        "watchfiles",
        "filelock",
        "docling",
        "httpcore.http11",
        "httpx",
        "httpcore.connection",
        "chromadb.config",
        "fsspec.local",
        "llama_index.core.readers.file.base"
    ]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
