from .base import Base 
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import text, String
import uuid


class MCPConfig(Base):
    
    __tablename__ = "mcp_config"

    id: Mapped["UUID"] = mapped_column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))

    name: Mapped[str] = mapped_column(String(255), nullable=False, description="The name of the MCP server")

    # TODO: Finish me (include things like URL, Headers, Env Variables, Arguments, Commands , Transport Type, Timeout, etc)
