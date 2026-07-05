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
    # Jira Configurations
    ###########################
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""

    
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

    # Encoding to fall back to when tiktoken doesn't recognize the configured model.
    OPENAI_FALLBACK_TIKTOKEN_ENCODING: str = "o200k_base"

    ###########################
    # Azure Configurations
    ###########################
    AZURE_API_KEY: str | None = None

    AZURE_OPENAI_API_BASE: str | None = None
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    AZURE_STANDARD_API_BASE: str | None = None

    # Model name -> Azure deployment overrides
    AZURE_OPENAI_DEPLOYMENT_MAP: dict[str, str] = {
        "gpt-5.1": "gpt-51",
    }

    # Context windows for models unknown to LlamaIndex (OpenAILike route)
    # TODO: add Gemini entries once its streaming is fixed
    AZURE_CONTEXT_WINDOW_OVERRIDES: dict[str, int] = {
        "claude-sonnet-4-5": 200000,
        "claude-opus-4-6": 200000,
    }

    # Fallback context window for unlisted models
    AZURE_DEFAULT_CONTEXT_WINDOW: int = 128000

    # Set True when the Azure endpoint is a MULTI-VENDOR gateway that also fronts
    # non-OpenAI models
    AZURE_MULTI_VENDOR_GATEWAY: bool = False
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

    # Base URL and API version for hosted OpenAI-compatible embedding gateways.
    # Same convention as AZURE_OPENAI_API_BASE (stops before `/openai`). The API
    # key used depends on the Selected EMBEDDING_PROVIDER.
    EMBEDDING_API_BASE: str | None = None
    EMBEDDING_API_VERSION: str = "2024-10-21"
    # Hard cap the embedding endpoint accepts; enforced as a safety net before embedding.
    EMBEDDING_MAX_TOKENS: int = 8191
    # Target chunk size in tokens (kept well below EMBEDDING_MAX_TOKENS for coherent chunks).
    CHUNK_TARGET_TOKENS: int = 512
    EMBEDDING_BATCH_SIZE: int = 64 # chunks per embedding request (reduce total requests to handle 429's)
    EMBEDDING_NUM_WORKERS: int = 2
    EMBEDDING_MAX_CHARS_PER_CHUNK: int = 8192
    CROSS_ENCODING_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    EMBEDDING_CACHE_CAPACITY: int = 5

    # Max prebuilt BM25 retrievers held in memory. Each caches a full data-source
    # corpus + term index (can be hundreds of MB), so keep this small. Override in .env.
    BM25_RETRIEVER_CACHE_CAPACITY: int = 4

    ###########################
    # API & Secret Keys 
    ###########################
    GITHUB_SECRET_TOKEN: str | None = None
    HUGGING_FACE_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    BITBUCKET_USERNAME: str | None = None
    BITBUCKET_SECRET_TOKEN: str | None = None
    BITBUCKET_MAX_CONCURRENT_DOWNLOADS: int = 3
    BITBUCKET_DOWNLOAD_TIMEOUT_SECONDS: float = 30.0
    RELEASE_BRANCH_PATTERN: str | None = None

    # number of nodes written to the DocStore per batch
    DOCSTORE_INSERT_BATCH_SIZE: int = 512

    # number of nodes per Chroma insert request
    CHROMA_INSERT_BATCH_SIZE: int = 64

    # page size when scanning a Chroma collection (collection.get)
    CHROMA_GET_PAGE_SIZE: int = 10000

    CONFLUENCE_EMAIL: str | None = None
    CONFLUENCE_SECRET_TOKEN: str | None = None

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
        "llama_index.core.readers.file.base",
        "llama_index.core.node_parser.node_utils",
        "openai._base_client" # NOTE: Remove me if we want to see exactly what requests we're making during Agentic Workflow
    ]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
