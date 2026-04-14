from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflow import get_agentic_workflow
from app.llm import LLMBase
from app.services.mcp import MCPService
from app.services.data_source import DataSourceService
from typing import AsyncGenerator, Any
import logging 

from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (AgentStream, ToolCallResult, AgentWorkflow)
from llama_index.core.llms import ChatMessage

logger = logging.getLogger(__name__)

class AgentService:
    """
    Service to handle the full "agent" life cycle that will be performed whenever we prompt it 
    """

    def __init__(
        self, 
        db: AsyncSession, 
        mcp_svc: MCPService, 
        data_source_svc: DataSourceService
    ) -> None:

        self.db = db
        self.mcp_svc = mcp_svc
        self.data_source_svc = data_source_svc


    async def run_agent(self, llm: LLMBase, user_prompt: str, conversation_history: list[ChatMessage], project_id: UUID) -> AsyncGenerator[str, None]:
        """
        Functionality to run the Agentic layer, leveraging MCP tooling and internal tooling 
        """

        # 1. Retrieve the Data Sources associated with the Project 
        data_sources: list[dict[str, Any]] = self.data_source_svc.get_project_data_sources(project_id)
        if not data_sources:
            logger.error(f"No Data Sources found for Project ID: {project_id}")
            raise Exception(f"Unable to retreive Context for the provided Question given the lack of Data Sources associated with the selected Project: {project_id}")

        # 2. Get relevant MCP tooling 
        mcp_tools: list[FunctionTool] = await self.mcp_svc.get_mcp_tools(data_sources, project_id) 
        logger.info(f"Retrieved {len(mcp_tools)} MCP tools")

        # 3. Get relevant internal tooling
        internal_tools = await self.get_internal_tools(project_id) 
        logger.info(f"Retrieved {len(internal_tools)} internal tools")

        # TODO: Merge the internal tooling and the MCP tools together 

        # TODO: Pass list of Data Sources to agentic workflow and have workflow extract relevant data 
        # required for MCP usage without prompting user (i.e URL for repository, etc)

        # 4. Get Agent Workflow & pass relevant tools to be leveraged 
        workflow: AgentWorkflow = get_agentic_workflow(mcp_tools, llm, data_sources)
        handler = workflow.run(user_msg=user_prompt, chat_history=conversation_history) 

        # 5. Stream events back to user
        async for event in handler.stream_events():
            if isinstance(event, AgentStream):
                if event.delta:
                    yield event.delta
            elif isinstance(event, ToolCallResult):
                logger.info(f"Tool called: {event.tool_name} -> {event.tool_output}")
            elif hasattr(event, "msg"):
                logger.info(f"Agent Message: {event.msg}")
        
        # 6. Wait for the final result
        result = await handler
        logger.info(f"Workflow Complete. Result: {result}")


    async def get_internal_tools(self, project_id):
        """
        TODO: This is where we can go through and setup the relevant RAG tool that will allow the Agent to query the vector database 

        The vector DB will have all the relevant context for the Project (Documentation & Code), allowing for quick Context gain for additional searches 

        """

        return []



        
        



        

        


        
        
