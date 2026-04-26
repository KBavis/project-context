from collections import defaultdict
from uuid import UUID
from contextlib import AsyncExitStack
from typing import AsyncGenerator, Any, Type
import logging

from workflows.handler import WorkflowHandler
from workflows.context.context import Context
from app.pydantic.streaming import StreamEventType
from app.services.util import format_sse_event
from app.pydantic.agent import AgentName, AgentType
from sqlalchemy.ext.asyncio import AsyncSession

from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from app.agents import get_agentic_workflow
from app.llm import LLMBase
from app.services.mcp import MCPService
from app.services.data_source import DataSourceService
from app.models.data_source import DataSourceType


from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (AgentOutput, AgentSetup, AgentStream, ToolCall, ToolCallResult, AgentWorkflow, AgentInput)
from llama_index.core.llms import ChatMessage
from llama_index.core.workflow import Event


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

            # Create shared Context for global state across agents
            ctx = Context(workflow)

            handler = workflow.run(
                user_msg=user_prompt,
                chat_history=conversation_history,
                ctx=ctx,
                max_iterations=40,
            )

            # 5. Stream events back to user
            try:
                async for event in handler.stream_events():

                    # handle workflow events based on Event Type 
                    # TODO: Instead of just logging, this should get updated to stream some of the relevant information back to user 
                    match event:

                        # agent streaming information 
                        case AgentStream():
                            if event.delta:

                                # finalized answer from our Synthesis Agent
                                if event.current_agent_name == AgentName.SYNTH:
                                    yield format_sse_event(StreamEventType.CHUNK, event.delta), event.delta

                                # Keep stream logging lightweight; response is cumulative and gets very noisy.
                                logger.debug(
                                    "AgentStreamEvent (Delta): Agent=%s, DeltaLen=%d, Delta=%r, ToolCalls=%d",
                                    event.current_agent_name,
                                    len(event.delta),
                                    event.delta[:200],
                                    len(event.tool_calls or []),
                                )

                            # Log internal agent thinking deltas separately.
                            if event.thinking_delta:
                                logger.debug(
                                    "AgentStreamEvent (Thinking): Agent=%s, ThinkingDeltaLen=%d, ThinkingDelta=%r",
                                    event.current_agent_name,
                                    len(event.thinking_delta),
                                    event.thinking_delta[:200],
                                )
                        
                        # handle Agent Input Events 
                        case AgentInput():
                            logger.debug(f"AgentInputEvent Uncovered: Agent={event.current_agent_name}, Inputs={event.input}")
                        

                        # handle Agent Setups 
                        case AgentSetup():
                            logger.debug(f"AgentSetupEvent Uncovered: Agent={event.current_agent_name}, Inputs={event.input}")
                        

                        # handle Agent Ouptut 
                        case AgentOutput():
                            logger.debug(
                                "AgentOutputEvent: Agent=%s, Response=%s, StructuredResponse=%s, ToolCalls=%s",
                                event.current_agent_name,
                                event.response,
                                event.structured_response,
                                event.tool_calls,
                            )

                        
                        # handle Agent Tool Calls 
                        case ToolCall():
                            logger.debug(f"ToolCallEvent Uncovered: ToolName={event.tool_name}, Arguments={event.tool_kwargs}")

                        # handle Tool Call Result 
                        case ToolCallResult():
                            logger.debug(f"ToolCallResultEvent Unconvered: ToolName={event.tool_name}, ToolOutput={event.tool_output}")
                        
                        # default 
                        case _:
                            logger.debug(f"Unknown Event Type Processed: {event}")


                
                # 6. Wait for the final result
                result = await handler
                logger.info(f"Workflow Complete. Result: {result}")

                # Log accumulated research state from shared Context
                await self._log_research_state(ctx)

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
    


    async def _extract_agent_workflow_information(self, event: Event, type: Type):
        """
        Log out relevant information based on the current state of the Agentic Wofklow 
        Information that is "relevant" will differ based on the event being performed 

        There are also certain scenarios where we would want to yield this information back to calling user
        """

        # TODO: Implement me 

        return 




    
    async def _log_research_state(self, ctx: Context) -> None:
        """
        Reads accumulated findings from the shared Context store and logs them.
        Called after the workflow completes to provide a debug view of everything
        the agents discovered during the session.
        """
        try:
            store = ctx.store
            findings = await store.get("findings", [])  # type: ignore[arg-type]
            if findings:
                logger.info(f"Research State — {len(findings)} findings accumulated:")
                for i, f in enumerate(findings, 1):
                    logger.info(f"  [{i}] {f.get('source', 'unknown')}: {f.get('finding', 'no summary')}")
            else:
                logger.info("Research State — no findings were recorded in shared state.")
        except Exception as state_err:
            logger.warning(f"Could not read research state from Context: {state_err}")


    async def get_internal_tools(self, project_id):
        """
        TODO: This is where we can go through and setup the relevant RAG tool that will allow the Agent to query the vector database 

        The vector DB will have all the relevant context for the Project (Documentation & Code), allowing for quick Context gain for additional searches 

        """

        return []



        
        



        

        


        
        
