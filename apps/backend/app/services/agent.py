from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflow import get_agentic_workflow
from app.llm import LLMBase
from app.services.mcp import MCPService
from typing import AsyncGenerator, Any
import logging 

from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (AgentStream, ToolCallResult)

logger = logging.getLogger(__name__)

class AgentService:
    """
    Service to handle the full "agent" life cycle that will be performed whenever we prompt it 
    """

    def __init__(
        self, 
        db: AsyncSession, 
        mcp_svc: MCPService
    ) -> None:

        self.db = db
        self.mcp_svc = mcp_svc


    async def run_agent(self, llm: LLMBase, user_prompt: str, conversation_history: str, project_id: UUID) -> AsyncGenerator[str, None]:
        """
        Functionality to run the Agentic layer, leveraging 
        """


        # 1. Get relevant MCP tooling 
        yield "Retreiving relevant MCP tooling"
        mcp_tools: list[FunctionTool] = await self.mcp_svc.get_mcp_tools(project_id) 
        logger.info(f"Retreived {len(mcp_tools)} MCP tools")

        # 2. Get relevant internal tooling
        yield "Retreiving relevant internal tooling"
        internal_tools = await self.get_internal_tools(project_id) 
        logger.info(f"Retreived {len(internal_tools)} internal tools")

        # 3. Get Agent Workflow & pass relevant tools to be leveraged 
        workflow = get_agentic_workflow(mcp_tools, llm)
        handler = workflow.run(user_msg=user_prompt)

        # 4. Stream events back to user
        async for event in handler.stream_events():
            logger.info(f"Received Workflow Event: {type(event).__name__}")
            if isinstance(event, AgentStream):
                if event.delta:
                    yield event.delta
            elif isinstance(event, ToolCallResult):
                logger.info(f"Tool called: {event.tool_name} -> {event.tool_output}")
            elif hasattr(event, "msg"):
                logger.info(f"Agent Message: {event.msg}")
        
        # 5. Wait for the final result
        result = await handler
        logger.info(f"Workflow Complete. Result: {result}")


    async def get_internal_tools(self, project_id):
        """
        TODO: This is where we can go through and setup the relevant RAG tool that will allow the Agent to query the vector database 

        The vector DB will have all the relevant context for the Project (Documentation & Code), allowing for quick Context gain for additional searches 

        """

        return []



        
        



        

        


        
        
