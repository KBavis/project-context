from __future__ import annotations
from typing import ClassVar
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import logging
import sys

# TODO: There may be a better way to handle the excess configs we have here, maybe having "generic" settings VS "llm" settings

# TODO: Move constants to constants.py and leave configurable values in herer 
class Settings(BaseSettings):

    PROJECT_NAME: str = "Contextualized"

    PYTHONDONTWRITEBYTECODE: int = 1
    
    ###########################
    # Database Configurations 
    ###########################
    SYNC_REL_DB_URL: str = ""
    ASYNC_REL_DB_URL: str = ""
    CHUNKS_DOC_STORE: str = "chunks_docstore"

    ###########################
    # Vector Database Configurations 
    ###########################
    VECTOR_DB_HOST: str = "localhost"
    VECTOR_DB_PORT: int = 8000

    ###########################
    # Ollama Specifications 
    ###########################
    OLLAMA_LOCAL_HOST_URL: str = "http://localhost:11434"
    OLLAMA_KV_CACHE_TYPE: str = "f16"
    OLLAMA_MODEL_TOKENIZER: str = "openai/gpt-oss-20b" # TODO: Find nice way to map Ollama model name to corresponding HuggingFace tokenizer based on model name (similar to tiktoken for openai)

    ###########################
    # LLM Specifications 
    ###########################
    LL_MODEL_PROVIDER: str = "Ollama"
    LL_MODEL: str = "gpt-oss:latest"
    LLM_EXPECTED_RESPONSE_SIZE: int = 500 
    LL_MODEL_CHAT_SUMMARY_SYSTEM_PROMPT: str = """
    Your goal is to take the following prompt from the user, along with some basic context such as the Project Name, and construct a high 
    quality, concise, and informative summary of the user's intent. These summary should be no more than 8 words and should clearly convery 
    what the user is attempting to achieve in the particular conversation
    """
    

    ###########################
    # Embedding Specifications 
    ###########################
    EMBEDDING_PROVIDER: str = "HuggingFace"
    EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"

    CROSS_ENCODING_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    EMBEDDING_CACHE_CAPACITY: int = 5

    ###########################
    # API & Secret Keys 
    ###########################
    GITHUB_SECRET_TOKEN: str | None = None
    HUGGING_FACE_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    ###########################
    # File Paths 
    ###########################
    TMP: str | None = "/tmp/contextualized"
    PROCESSED_DIR: str | None = "/processed"
    TMP_DOCS: str | None = "/tmp/contextualized/docs"
    TMP_CODE: str | None = "/tmp/contextualized/code"

    ###########################
    # Environment 
    ###########################
    ENV: str | None = "dev"


    ###########################
    # Docling Configurations 
    ###########################
    DOCLING_ACCELERATOR_DEVICE: str | None = "cpu"

    ###########################
    # Validation Constants 
    ###########################
    VALID_DATA_PROVIDERS: set[str] = {"GitHub", "BitBucket", "Confluence"}

    VALID_LL_MODEL_PROVIDERS: set[str] = {"OpenAI", "Ollama"} # TODO: Add additional providers for configured LLM's 


    ###########################
    # File Extensions 
    ###########################
    CODE_FILE_EXTENSIONS: set[str] = {
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

    EXTENSION_TO_LANGUAGE: dict[str, str] = {
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

    DOCS_FILE_EXTENSIONS: set[str] = {"docx", "pdf", "md"}

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        extra='ignore',
        env_file=Path(__file__).resolve().parents[2] / ".env", env_file_encoding="utf-8"
    )


settings = Settings()

_LEVEL_BY_ENV: dict[str, int] = {"prod": logging.INFO, "dev": logging.DEBUG}


def setup_logging():
    """
    Configure root logger
    """

    root = logging.getLogger()

    root.handlers.clear()  # clear existing handlers

    env = settings.ENV.lower() if settings.ENV else "prod"
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
