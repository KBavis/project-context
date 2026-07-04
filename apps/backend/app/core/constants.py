from __future__ import annotations
DOCS = "DOCS"
CODE = "CODE"




VALID_LL_MODEL_PROVIDERS: set[str] = {"OpenAI", "Ollama", "Azure"}

CODE_FILE_EXTENSIONS: set[str] = {
    "c", "cpp", "cs", "java", "js", "jsx", "ts", "tsx", "py", "php",
    "html", "css", "swift", "rb", "pl", "sh", "sql", "json", "yaml", "yml", "xml"
}

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    "py": "python", "js": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript", "java": "java",
    "c": "c", "cpp": "cpp", "cs": "csharp", "rb": "ruby",
    "php": "php", "swift": "swift", "pl": "perl", "sh": "bash",
    "sql": "sql", "html": "html", "css": "css", "json": "json",
    "yaml": "yaml", "yml": "yaml", "xml": "xml"
}

DOCS_FILE_EXTENSIONS: set[str] = {"docx", "pdf", "md"}

INGESTION_EXCLUDE_PATTERNS: list[str] = [
    "*/node_modules/*", "*/vendor/*", "*/dist/*", "*/build/*",
    "*.min.js", "*.min.css", "*.map", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "composer.lock", "go.sum",
]

INGESTION_EXCLUDE_PATTERNS_EXTRA: list[str] = []
