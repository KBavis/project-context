from pydantic import BaseModel
from enum import Enum

class CodeFileExtension(str, Enum):
    C = "c"
    CPP = "cpp"
    CS = "cs"
    JAVA = "java"
    JS = "js"
    JSX = "jsx"
    TS = "ts"
    TSX = "tsx"
    PY = "py"
    PHP = "php"
    HTML = "html"
    CSS = "css"
    SWIFT = "swift"
    RB = "rb"
    PL = "pl"
    SH = "sh"
    SQL = "sql"
    XML = "xml"
    JSON = "json"
    YAML = "yaml"
    YML = "yml"


class DocsFileExtension(str, Enum):
    DOCX = "docx"
    PDF = "pdf"
    MD = "md"


class FileProcesingStatus(Enum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    NEW = "new"
    MOVED = "moved"
    COPIED = "copied"
    NOT_FOUND = "not_found"
    MISSING_PROJECT_LINKS = "missing_project_links"


class File(BaseModel):
    path: str
    file_name: str 
    file_type: CodeFileExtension | DocsFileExtension
    size: int # number of bytes in file
    hash: str # hash based on file content 
