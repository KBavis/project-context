from __future__ import annotations
from pydantic import BaseModel
from enum import Enum
from uuid import UUID

from app.models.mcp_config import MCPTransportType

class Command(str, Enum):
    NPX = "npx"
    PYTHON = "python"
    NODE = "node"
    DOCKER = "docker"

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
    transport_type: MCPTransportType
    timeout: int
    config: StdioConfig | HttpConfig
    data_source_id: UUID
