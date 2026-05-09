from collections import defaultdict
from uuid import UUID
from contextlib import AsyncExitStack
from typing import AsyncGenerator
import logging
import json

from llama_index.core.base.llms.types import TextBlock
from workflows.context.context import Context
from app.pydantic.streaming import StreamEventType
from app.services.util import format_sse_event
from app.pydantic.agent import AgentName 
from sqlalchemy.ext.asyncio import AsyncSession

from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from app.agents import Tools, get_agentic_workflow
from app.llm import LLMBase
from app.services.mcp import MCPService
from app.services.data_source import DataSourceService
from app.models.data_source import DataSource, DataSourceType


from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (AgentOutput, AgentSetup, AgentStream, ToolCall, ToolCallResult, AgentWorkflow, AgentInput)
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
            data_sources: list[DataSource] = await self.data_source_svc.aget_project_data_sources(project_id)
            if not data_sources:
                logger.error(f"No Data Sources found for Project ID: {project_id}")
                raise Exception(f"Unable to retreive Context for the provided Question given the lack of Data Sources associated with the selected Project: {project_id}")

            # 2. Get relevant MCP tooling 
            mcp_tools: defaultdict[DataSourceType, list[FunctionTool]] = await self.mcp_svc.get_mcp_tools(data_sources, async_exit_stack) 
            total_tools = sum(len(tools) for tools in mcp_tools.values())
            logger.info(f"Retrieved {total_tools} MCP tools")

            # 3. Leverage LLM to determine what MCP tools and data sources will be relevant for answering the User's question 
            # TODO: Complete me 

            # 4. Get relevant internal tooling 
            tool_manager = Tools(data_sources, project_id) # TODO: Pass selected data sources here 
            internal_tools = await tool_manager.get_internal_tools() 
            if internal_tools:
                logger.info(f"Retrieved {len(internal_tools)} internal tools")
            else:
                logger.info("No internal tools were retrieved")

            # 5. Get Agent Workflow & pass relevant tools to be leveraged 
            token_counter = TokenCountingHandler()
            callback_manager = CallbackManager([token_counter])
            workflow: AgentWorkflow = get_agentic_workflow(mcp_tools, llm, data_sources, callback_manager=callback_manager)

            # 6. Run the Agent Workflow
            ctx = Context(workflow) # TODO: Can we view this shared Context?? Log it as it's updated?? Likely something like this 
            handler = workflow.run(
                user_msg=user_prompt,
                chat_history=conversation_history,
                ctx=ctx,
                max_iterations=40,
            )

            # 7. Stream events back to user
            # TODO: This function is getting blaoted and messy, refactor some of this code 
            try:
                async for event in handler.stream_events():

                    # handle workflow events based on Event Type 
                    # TODO: Instead of just logging, this should get updated to stream some of the relevant information back to user 
                    match event:
                        
                        case AgentStream():
                            # stream agent's response back to calling user 
                            if event.delta and event.current_agent_name == AgentName.SYNTH:
                                yield format_sse_event(StreamEventType.CHUNK, event.delta), event.delta
                                continue
                                
                            # NOTE: If we're seeing information getting streamed, but it's not from SynthAgent, this is the "Agent's Internal Dialogue"
                            # This can either be directly from the `event.delta``, or if it's a reasoning model, could be the `event.thinking_delta`
                            if event.delta or event.thinking_delta:
                                
                                # TODO: Once we start testing out reasoning models, it may be a good idea to have this information streamed back to calling user 
                                # that way, the end user is getting periodic insights into what/why a Agent is doing something. For time being, we can just log this information out
                                logger.debug(
                                    "AgentStreamEvent (%s): Agent=%s, InternalDialogue:%s, ToolCalls=%d",
                                    "Thinking" if event.thinking_delta else "Delta",
                                    event.current_agent_name, 
                                    event.delta if event.thinking_delta else event.delta,
                                    len(event.tool_calls or [])
                                )

                        case AgentInput():
                            # extract relevant information
                            agent_name = event.current_agent_name
                            latest_message = await self._extract_latest_message(event)
                            logger.debug(
                                "AgentInputEvent: Agent=%s, LatestMessage=%s", 
                                agent_name,
                                latest_message
                            )
                        

                        case AgentOutput():
                            agent_name = event.current_agent_name
                            tool_breakdown = []

                            for tool_call in event.tool_calls:
                                tool_name = tool_call.tool_name
                                tool_args = tool_call.tool_kwargs

                                if tool_name == "handoff":
                                    handoff_agent = tool_args.get("to_agent")
                                    handoff_reason = tool_args.get("reason")

                                    if not handoff_reason or not handoff_agent:
                                        logger.warning(f"Invalid state for `handoff` tool call, this tool call will fail. CurrentState={tool_call}")
                                        continue

                                    reasons = await self._safe_parse_handoff_reason(handoff_reason)
                                    tool_breakdown.append({
                                        "Tool Name": tool_name,
                                        "Handoff Agent": handoff_agent,
                                        "Goal": reasons.get("intent", ""),
                                        "Requires Code Agent": reasons.get("needs_code", ""),
                                        "Requires Doc Agent": reasons.get("needs_docs", ""),
                                        "Question Class": reasons.get("question_class", "Unknown Question Class"),
                                        "Search Hints": reasons.get("search_hints", {}),
                                        "Plan of Action": reasons.get("plan", []),
                                    })
                                else:
                                    tool_breakdown.append({
                                        "Tool Name": tool_name,
                                        "Tool Arguments": tool_args,
                                    })
                            logger.debug("AgentOutputEvent: Agent=%s, ToolBreakown=%s", agent_name, tool_breakdown)
                                                                

                        
                        case ToolCall():
                            logger.debug("ToolCallEvent: Name=%s, Arguments=%s", event.tool_name, event.tool_kwargs)
                        case ToolCallResult():
                            try:
                                summary = " | ".join(
                                    block.text[:200]
                                    for block in event.tool_output.blocks
                                    if isinstance(block, TextBlock)
                                )
                            except Exception:
                                summary = str(event.tool_output)[:300]

                            logger.debug("ToolCallResultEvent: Name=%s, Output=%s", event.tool_name, summary)
                        
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
    
    async def _safe_parse_handoff_reason(self, handoff_reason) -> dict:
        if isinstance(handoff_reason, dict):
            return handoff_reason
        if not handoff_reason or not handoff_reason.strip():
            logger.warning(f"No hand off reason extracted, returning empty dictionary")
            return {}  # or log a warning here
        try:
            return json.loads(handoff_reason)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse handoff_reason: {e}. Raw value: {repr(handoff_reason)}")
            return {}

    async def _extract_latest_message(self, event: AgentInput) -> dict:
        """
        Extract latest message from a particular AgentInput Event for debugging purposes 

        Args:
            event (AgentInput): the event that we want to extract system prompt from 
        """
        
        # extract latest message 
        latest_input = event.input[-1] if event.input else None 
        if not latest_input:
            raise Exception("No input messages available: Agent in corrupt state")

        latest_message_text = "".join(
            block.text for block in latest_input.blocks if isinstance(block, TextBlock)
        )
        latest_message = {
            "message": latest_message_text,
            "role": latest_input.role
        }
        
        return latest_message



    
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



        
        



        

        


        
        
