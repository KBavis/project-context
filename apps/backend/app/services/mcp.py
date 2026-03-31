from uuid import UUID
import logging 

from app.models import MCPConfig
from app.models.mcp_config import MCPTransportType
from app.pydantic import MCPConfig as PydanticMCPConfig, HttpConfig, StdioConfig

from sqlalchemy.orm import Session
from sqlalchemy import select


logger = logging.getLogger(__name__)

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

        # validate the MCP Configuration request
        self._validate_mcp_config_request_fields(mcp_config)

        # attempt to retrieve MCP by provided information 
        mcp = self.get_mcp(mcp_config)
        if mcp:
            logger.info(f"Found existing MCP Configuration with ID {mcp.id}")
            return mcp
        
        logger.info("No existing MCP Configuration found, attempting to create new MCP Configuration")
        return self.create_mcp(mcp_config)



    def get_mcp(self, mcp_config: PydanticMCPConfig) -> MCPConfig | None:
        """
        Get an MCP Configuration corresponding to the provided MCP Configuration

        TODO: FINISH ME!

        Args:
            mcp_config: The MCP Configuration to get
        """
        
        # conditionally determine which fields to filter on based on transport type 
        stmt = (
            select(MCPConfig)
            .where(MCPConfig.name == mcp_config.name)
            .where(MCPConfig.config.get("url", None) == mcp_config.config.url)
            .where(MCPConfig.config.get("headers", None) == mcp_config.config.headers)
        ) if mcp_config.transport_type == MCPTransportType.HTTP else (
            select(MCPConfig)
            .where(MCPConfig.name == mcp_config.name)
            .where(MCPConfig.command == mcp_config.command)
            .where(MCPConfig.args == mcp_config.args)
            .where(MCPConfig.env_variables == mcp_config.env_variables)
            .where(MCPConfig.cwd == mcp_config.cwd)
        )

        res = self.db.execute(stmt)
        return res.scalar_one_or_none()
        
    

    def create_mcp(self, mcp_config: PydanticMCPConfig) -> MCPConfig:
        """
        Create an MCP Configuration corresponding to the provided MCP Configuration

        Args:
            mcp_config: The MCP Configuration to create
        """

    def get_mcp_configs(self) -> list[MCPConfig]:
        """
        Get all MCP Configurations
        """
        return list(self.db.execute(select(MCPConfig)).scalars().all())

    def get_mcp_by_id(self, id: UUID) -> MCPConfig | None:
        """
        Get an MCP Configuration by its ID

        Args:
            id: The ID of the MCP Configuration to get
        """
        mcp_config = self.db.execute(select(MCPConfig).where(MCPConfig.id == id)).scalar_one_or_none()
        if not mcp_config:
            raise Exception(f"MCP Configuration with ID {id} not found")
        return mcp_config
    

    def _validate_mcp_config_request_fields(self, mcp_config: PydanticMCPConfig):
        """
        Validate the provided MCP Configuration request

        Args:
            mcp_config: The MCP Configuration request to validate
        """
        
    

    def _validate_mcp_config_request_happy_path(self, mcp_config: PydanticMCPConfig):
        """
        Validate the provided MCP Configuration request by performing a "happy path" request to the MCP server

        Args:
            mcp_config: The MCP Configuration request to validate
        """

        if (mcp_config.transport_type == MCPTransportType.HTTP and not isinstance(mcp_config.config, HttpConfig)):
            raise ValueError("Invalid MCP Configuration: HTTP transport type requires HttpConfig")
        
        if (mcp_config.transport_type == MCPTransportType.STDIO and not isinstance(mcp_config.config, StdioConfig)):
            raise ValueError("Invalid MCP Configuration: STDIO transport type requires StdioConfig")

        