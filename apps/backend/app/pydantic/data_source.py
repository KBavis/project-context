from __future__ import annotations
from pydantic import BaseModel
from typing import List
from .mcp import MCPConfig


class CreateDataSourceRequest(BaseModel):
    data_source: DataSourceRequest
    mcp_config: MCPConfig | None # optional creation of MCP in tandem with data source 

class DataSourceRequest(BaseModel):
    provider: str
    url: str
    name: str
    branch: str | None = None
    project_ids: List[str] = []  # list of Jira Epics corresponding to this DataSource
