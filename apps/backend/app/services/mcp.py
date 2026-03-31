from uuid import UUID
import logging 
import asyncio

from app.models import MCPConfig
from app.models.mcp_config import MCPTransportType
from app.pydantic import MCPConfig as PydanticMCPConfig, HttpConfig, StdioConfig

from sqlalchemy.orm import Session
from sqlalchemy import Select, select

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


logger = logging.getLogger(__name__)

class MCPService:
    """
    Service for handling MCP creation and retrieval 

    """
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

        Args:
            mcp_config: The MCP Configuration to get
        """

        # conditionally determine which fields to filter on based on transport type 
        stmt = self._get_mcp_stmt(mcp_config)
        
        res = self.db.execute(stmt)
        return res.scalar_one_or_none()

    def _get_mcp_stmt(self, mcp_config: PydanticMCPConfig) -> Select[tuple[MCPConfig]]:
        """
        Get the statement for retrieving an MCP Configuration

        Args:
            mcp_config: The MCP Configuration to get
        """

        if mcp_config.transport_type == MCPTransportType.HTTP:
            if not isinstance(mcp_config.config, HttpConfig):
                raise ValueError("Invalid MCP Configuration: HTTP transport type requires HttpConfig")

            http_config: HttpConfig = mcp_config.config 
            return (
                select(MCPConfig)
                .where(MCPConfig.name == mcp_config.name)
                .where(MCPConfig.config["url"] == http_config.url)
                .where(MCPConfig.config["headers"] == http_config.headers)
            )
        elif mcp_config.transport_type == MCPTransportType.STDIO:
            if not isinstance(mcp_config.config, StdioConfig):
                raise ValueError("Invalid MCP Configuration: STDIO transport type requires StdioConfig")

            stdio_config: StdioConfig = mcp_config.config 
            return (
                select(MCPConfig)
                .where(MCPConfig.name == mcp_config.name)
                .where(MCPConfig.config["command"] == stdio_config.command)
                .where(MCPConfig.config["args"] == stdio_config.args)
                .where(MCPConfig.config["env_variables"] == stdio_config.env_variables)
                .where(MCPConfig.config["cwd"] == stdio_config.cwd)
            )
        else:
            raise ValueError(f"Invalid MCP Configuration: Unknown transport type {mcp_config.transport_type}")
            

    def create_mcp(self, mcp_config: PydanticMCPConfig) -> MCPConfig:
        """
        Create an MCP Configuration corresponding to the provided MCP Configuration

        Args:
            mcp_config: The MCP Configuration to create
        """
        # validate the MCP Configuration request by performing a "happy path" request to the MCP server
        asyncio.run(self._validate_mcp_server_handshake(mcp_config))

        # create the MCP Configuration
        model = MCPConfig(
            name=mcp_config.name,
            transport_type=mcp_config.transport_type,
            config=mcp_config.config.model_dump(),
            timeout=mcp_config.timeout,
        )

        self.db.add(model)
        self.db.flush()

        return model

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
        if (mcp_config.transport_type == MCPTransportType.HTTP and not isinstance(mcp_config.config, HttpConfig)):
            raise ValueError("Invalid MCP Configuration: HTTP transport type requires HttpConfig")
        
        if (mcp_config.transport_type == MCPTransportType.STDIO and not isinstance(mcp_config.config, StdioConfig)):
            raise ValueError("Invalid MCP Configuration: STDIO transport type requires StdioConfig")
    

    async def _validate_mcp_server_handshake(self, mcp_config: PydanticMCPConfig):
        """
        Validate the provided MCP Configuration request by performing a "happy path" request to the MCP server

        TODO: Implement me 

        Args:
            mcp_config: The MCP Configuration request to validate
        """

        if mcp_config.transport_type == MCPTransportType.HTTP:
            # TODO: Make the request to HTTP Server and validate the response 
            raise Exception("Not implemented")
        elif mcp_config.transport_type == MCPTransportType.STDIO:
            # ensure stdio_config is a StdioConfig
            stdio_config: StdioConfig | None = mcp_config.config if isinstance(mcp_config.config, StdioConfig) else None
            if not stdio_config:
                raise ValueError("Invalid MCP Configuration: STDIO transport type requires StdioConfig")
            await self.perform_stdio_happy_path(stdio_config)
        else:
            raise Exception(f"Invalid MCP Configuration: Unknown transport type {mcp_config.transport_type}")
    

    async def perform_stdio_happy_path(self, stdio_config: StdioConfig):
        """
        Perform validation on the provided STDIO configuration

        Args:
            stdio_config: The STDIO configuration to validate
        """
        
        server_params = StdioServerParameters(
            command = stdio_config.command,
            args = stdio_config.args,
            env = stdio_config.env_variables,
            cwd = stdio_config.cwd,
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:

                # 1. Initlaize session
                await session.initialize()

                # 2. List Tools 
                tools_result = await session.list_tools() 
                if not tools_result.tools:
                    raise Exception(f"MCP Server with configuration {stdio_config} has no available tools")

                # 3. List Resources
                resources_result = await session.list_resources()
                if not resources_result.resources:
                    raise Exception(f"MCP Server with configuration {stdio_config} has no available resources")

                
                #TODO: Consider running "happy path tool" here (not sure if there is a standard no-arg tool we can leverage here )

                
            


                