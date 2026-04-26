from collections import defaultdict
from uuid import UUID
from contextlib import AsyncExitStack
from typing import AsyncGenerator, Any
import asyncio
import json
import logging

from workflows.handler import WorkflowHandler
from app.pydantic.streaming import StreamEventType
from app.services.util import format_sse_event

from sqlalchemy.ext.asyncio import AsyncSession

from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from app.agents import get_agentic_workflow
from app.llm import LLMBase
from app.services.mcp import MCPService
from app.services.data_source import DataSourceService
from app.models.data_source import DataSourceType


from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (AgentStream, ToolCall, ToolCallResult, AgentWorkflow, AgentInput)
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


    async def run_agent(self, llm: LLMBase, user_prompt: str, conversation_history: list[ChatMessage], project_id: UUID) -> AsyncGenerator[tuple[str, str | dict | None], None]:
        """
        Functionality to run the Agentic layer, leveraging MCP tooling and internal tooling 
        """

        """
        NOTE: The reason for AsyncExitStack is because we may need to have 
        multiple MCP servers connected at once, so we essentially need a "bag of context 
        managers" that we can enter and exit as needed throughout the course 
        of the agent running. 

        IF we only had a single MCP server, we could simply do something like "async with mcp_client" 
        and that would handle the connection lifecycle for us. 

        Without this, we run into issues where the MCP Client rapidly is opening and closing 
        connections, causing race conditions such as anyio.BrokenResourceError 
        """
        async with AsyncExitStack() as async_exit_stack:

            # 1. Retrieve the Data Sources associated with the Project 
            data_sources: list[dict[str, Any]] = await self.data_source_svc.aget_project_data_sources(project_id)
            if not data_sources:
                logger.error(f"No Data Sources found for Project ID: {project_id}")
                raise Exception(f"Unable to retreive Context for the provided Question given the lack of Data Sources associated with the selected Project: {project_id}")

            # 2. Get relevant MCP tooling 
            mcp_tools: defaultdict[DataSourceType, list[FunctionTool]] = await self.mcp_svc.get_mcp_tools(data_sources, async_exit_stack) 
            total_tools = sum(len(tools) for tools in mcp_tools.values())
            logger.info(f"Retrieved {total_tools} MCP tools")

            # 3. Get relevant internal tooling
            internal_tools = await self.get_internal_tools(project_id) 
            logger.info(f"Retrieved {len(internal_tools)} internal tools")

            # TODO: Merge the internal tooling and the MCP tools together 

            # 4. Get Agent Workflow & pass relevant tools to be leveraged 
            token_counter = TokenCountingHandler()
            callback_manager = CallbackManager([token_counter])
            
            workflow: AgentWorkflow = get_agentic_workflow(mcp_tools, llm, data_sources, callback_manager=callback_manager)
            handler = workflow.run(
                user_msg=user_prompt,
                chat_history=conversation_history,
                max_iterations=40,
            )

            # 5. Stream events back to user
            try:
                async for event in handler.stream_events():
                    if isinstance(event, AgentStream):
                        # streaming back final answer back to user
                        if event.delta:
                            yield format_sse_event(StreamEventType.CHUNK, event.delta), event.delta
                    elif isinstance(event, ToolCall):
                        yield format_sse_event(StreamEventType.STATUS, await self._extract_tool_call_info(event), "Agent Thinking"), None
                    elif isinstance(event, ToolCallResult):
                        yield format_sse_event(StreamEventType.STATUS, f"Tool `{event.tool_name}` leveraged successfully.", "Tool Call"), None
                    elif hasattr(event, "msg"):
                        logger.info(f"Agent Message: {event.msg}")
                
                # 6. Wait for the final result
                result = await handler
                logger.info(f"Workflow Complete. Result: {result}")
            except Exception as e:
                logger.error(f"Error in agent workflow: {e}", exc_info=True)
                
                # Identify common LLM failures and map to user-friendly messages
                error_msg = str(e).lower()
                friendly_msg = "An unexpected error occurred during agent execution."
                
                if "context_length" in error_msg or "maximum context length" in error_msg:
                    friendly_msg = "Context window exceeded. Please try a shorter prompt or clear conversation history."
                elif "rate_limit" in error_msg or "429" in error_msg:
                    friendly_msg = "Rate limit reached. Please wait a moment before trying again."
                elif "timeout" in error_msg or "deadline exceeded" in error_msg:
                    friendly_msg = "The request timed out. The agent took too long to respond."
                
                # Yield the error event so the UI can display it immediately
                yield format_sse_event(StreamEventType.ERROR, friendly_msg, "Workflow Error"), None
                
                # Do NOT raise the exception here. Allow for token usage to be calculated and returned
                

            finally:
                # 7. Yield token usage data (always send what was consumed up to failure)
                yield StreamEventType.TOKEN_USAGE, {
                # Total tokens fed into the LLM (conversation history, system prompts, tool definitions, user prompt)
                    "input_tokens": token_counter.prompt_llm_token_count,
                # Total tokens generated by LLM during agentic workflow (final response, JSON blocks to call MCP, hidden text while thinking)
                    "output_tokens": token_counter.completion_llm_token_count, 
                # Input tokens + Output tokens
                    "total_tokens": token_counter.total_llm_token_count
                }

    async def _extract_tool_call_info(self, event: ToolCall) -> str:
        """
        Extracts the tool call information from the event
        """
        if "handoff" in event.tool_name.lower():
            reason = event.tool_kwargs.get("reason", "{}")
            if not reason:
                logger.info("No reason found in Tool Call, returning default message")
                return "Orchestrating next steps..."

            data = json.loads(reason) if not isinstance(reason, dict) else reason

            # log out plan for debugging 
            plan = data.get("plan", [])
            if plan:
                logger.info(f"Agentic Workflow Current Plan: {plan}")
            else:
                logger.info("No plan found")
            

            # log out research state (for debugging)
            state = data.get("research_state", {})
            if state:
                logger.info(f"Agentic Workflow Current State: {state}")
            else:
                logger.info("No state found")

            # pass back intent to UI for display
            intent = data.get("intent", "")
            if intent:
                return f"Goal: {intent}"
            else:
                return "Orchestrating next steps..."
        else:
            return f"Using tool `{event.tool_name}`..."



    async def get_internal_tools(self, project_id):
        """
        TODO: This is where we can go through and setup the relevant RAG tool that will allow the Agent to query the vector database 

        The vector DB will have all the relevant context for the Project (Documentation & Code), allowing for quick Context gain for additional searches 

        """

        return []



        
        



        

        


        
        
