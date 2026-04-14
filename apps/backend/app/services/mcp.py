from uuid import UUID
import logging 
import asyncio


import os
import traceback
from typing import Any

from app.models import DataSource, MCPConfig
from app.models.mcp_config import MCPTransportType
from app.pydantic import MCPConfig as PydanticMCPConfig, HttpConfig, StdioConfig

from sqlalchemy.orm import Session
from sqlalchemy import Select, select

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.services.data_source import DataSourceService

from llama_index.tools.mcp import BasicMCPClient, McpToolSpec
from llama_index.core.tools import FunctionTool


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
            data_source_id=mcp_config.data_source_id
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
    
    def delete_mcp(self, id: UUID):
        """
        Delete an MCP Configuration by its ID
        """
        mcp_config = self.get_mcp_by_id(id)
        self.db.delete(mcp_config)
        self.db.commit()
    

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

        logger.debug(f"Performing happy path for STDIO configuration: {stdio_config}")
        
        # ensure current environment is passed down (mandatory for finding binaries in PATH)
        env = os.environ.copy()
        if stdio_config.env_variables:
            env.update(stdio_config.env_variables)

        server_params = StdioServerParameters(
            command = stdio_config.command.value if hasattr(stdio_config.command, 'value') else str(stdio_config.command),
            args = stdio_config.args,
            env = env,
            cwd = stdio_config.cwd if stdio_config.cwd else None,
        )

        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    # 1. Initialize session (Handshake)
                    await session.initialize()
                    logger.info(f"Successfully initialized session for MCP: {stdio_config.command}")

                    # 2. Tiny warm-up sleep to avoid race conditions with some servers
                    await asyncio.sleep(0.1)

                    # 3. Verify we can at least list tools (even if empty)
                    await session.list_tools() 
                    
        except Exception:
            error_trace = traceback.format_exc()
            logger.error(f"Detailed MCP Connection Traceback:\n{error_trace}")
            raise Exception(f"MCP Connection Failed: A task-level error occurred during communication. Check backend logs for the full trace.")

                
    

    async def get_mcp_tools(self, data_sources: list[dict[str, Any]], project_id: UUID) -> list[FunctionTool]:
        """
        Retreive all MCP tools that are associated with a particular Project 

        Args:
            data_sources: The Data Sources associated with the Project
            project_id: The ID of the project
        """
        
        # get MCP servers associated with the data sources 
        mcp_server_ids = [ ds["mcp_config"]["id"] for ds in data_sources if ds["mcp_config"] ]
        if not mcp_server_ids:
            logger.info(f"No MCP Servers configured for the Project {project_id}, no tooling will be avaialble asside from internal tools")
            return []

        mcp_servers: list[MCPConfig] = []
        for server_id in set(mcp_server_ids):
            server = self.get_mcp_by_id(server_id)
            if server:
                mcp_servers.append(server)
        
        if not mcp_servers:
            logger.info(f"Unable to retreive MCP Servers for Project ID: {project_id}")
            return []

        # get tools associated with each MCP server 
        all_tools: list[FunctionTool] = []
        for mcp_server in mcp_servers:
            if mcp_server.transport_type == MCPTransportType.STDIO:


                    """
                        # TODO: Consider having MCP servers as a part of the Fast API life cycle 
                        Whenever we start up application, associated MCPs are started as well
                    """

                    # 1. setup MCP client 
                    client = await self.get_mcp_client(mcp_server)
                    await asyncio.sleep(0.5)

                    # 2. extract tools from MCP client
                    tool_spec = McpToolSpec(client=client)
                    all_tools.extend(await tool_spec.to_tool_list_async())

            elif mcp_server.transport_type == MCPTransportType.HTTP:
                client = await self.get_mcp_client(mcp_server)
                tool_spec = McpToolSpec(client=client)
                all_tools.extend(await tool_spec.to_tool_list_async())

        # return relevant tools to be leveraged by Agent
        return all_tools 
    



    async def get_mcp_client(self, mcp_server: MCPConfig):
        """
        Setup MCP Client for the provided MCP Server Configuration stored in Database 

        Args:
            mcp_server: The MCP Server Configuration to setup a client for
        """

        if mcp_server.transport_type == MCPTransportType.STDIO:
            env = os.environ.copy()
            stdio_config: StdioConfig = StdioConfig.model_validate(mcp_server.config) 
            if stdio_config.env_variables:
                env.update(stdio_config.env_variables)
            
            return BasicMCPClient(
                command_or_url=stdio_config.command,
                args=stdio_config.args,
                env=env
            )
        elif mcp_server.transport_type == MCPTransportType.HTTP:
            http_config: HttpConfig = HttpConfig.model_validate(mcp_server.config) 
            return BasicMCPClient(
                command_or_url=http_config.url,
                headers=http_config.headers,
                timeout=mcp_server.timeout,
            )
        else:
            raise Exception(f"Invalid MCP Configuration: Unknown transport type {mcp_server.transport_type}")



        


                