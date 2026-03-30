from uuid import UUID
from app.models import MCPConfig
from app.pydantic import MCPConfig as PydanticMCPConfig

from sqlalchemy.orm import Session
from sqlalchemy import select


class MCPService:
    def __init__(self, db: Session):
        self.db = db

    def find_or_create_mcp_config(self, mcp_config: PydanticMCPConfig) -> MCPConfig:
        """
        Find an existing MCP Configuration corresponding to the provided MCP Configuration, or 
        go through and create the MCP Configuration.

        Args:
            mcp_config: The MCP Configuration to find or create
        """
    

    def get_mcp(self, mcp_config: PydanticMCPConfig) -> MCPConfig | None:
        """
        Get an MCP Configuration corresponding to the provided MCP Configuration

        Args:
            mcp_config: The MCP Configuration to get
        """
    

    def create_mcp(self, mcp_config: PydanticMCPConfig) -> MCPConfig:
        """
        Create an MCP Configuration corresponding to the provided MCP Configuration

        Args:
            mcp_config: The MCP Configuration to create
        """
        
        

        