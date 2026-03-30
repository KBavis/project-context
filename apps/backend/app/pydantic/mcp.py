from __future__ import annotations
from pydantic import BaseModel
from enum import Enum

class Command(str, Enum):
    NPX = "npx"
    PYTHON = "python"
    NODE = "node"

class StdioConfig(BaseModel):
    command: Command
    args: list[str]
    cwd: str

    # optional env variables (these will be retrieved from settings dynamically to avoid user specifying these in request)
    env_variables: dict[str, str] | None = None

class HttpConfig(BaseModel):
    url: str
    headers: dict[str, str] | None = None


class MCPConfig(BaseModel):
    name: str
    transport_type: str
    timeout: int
    config: StdioConfig | HttpConfig
