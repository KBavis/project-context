from uuid import UUID
from .base import Base 
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import text, String, ForeignKey
from typing import TYPE_CHECKING

from enum import Enum
from sqlalchemy import Enum as SAEnum

# avoid warning
if TYPE_CHECKING:
    from .data_source import DataSource
    from .data_source_mcp import DataSourceMCPConfig


class MCPTransportType(Enum):
    STDIO = "stdio"
    HTTP = "http"

class MCPConfig(Base):
    
    __tablename__ = "mcp_config"

    id: Mapped["UUID"] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))

    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="The name of the MCP server")

    transport_type: Mapped[MCPTransportType] = mapped_column(SAEnum(MCPTransportType), nullable=False, comment="The transport type of the MCP server (i.e stdio, http)")

    timeout: Mapped[int] = mapped_column(nullable=False, comment="The timeout of the MCP server")

    """
    Local MCP (i.e transport_type = STDIO)
        - command (i.e npx, python, node)
        - args (i.e ["-y", "@modelcontextprotocol/server-openai"])
        - env_variables (i.e {"OPENAI_API_KEY": "sk-1234567890"})
        - cwd (directory where the command will be executed)
    
    Remote MCP (i.e transport_type = HTTP)
        - url (i.e "https://api.openai.com/v1/mcp")
        - headers (i.e {"Authorization": "Bearer sk-1234567890"})
    """
    config: Mapped[JSONB] = mapped_column(JSONB, nullable=False, comment="The configuration of the MCP server (i.e command, url, headers, env variables, arguments, etc)")

    # many to many relationship with DataSource
    data_source_mcp_configs: Mapped[list["DataSourceMCPConfig"]] = relationship(
        back_populates="mcp_config", cascade="all, delete-orphan"
    )
