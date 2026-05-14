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
from app.services.chunk_retrieval import ChunkRetrievalService
from app.models.data_source import DataSource

from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (AgentOutput, AgentSetup, AgentStream, ToolCall, ToolCallResult, AgentWorkflow, AgentInput)
from llama_index.core.llms import ChatMessage


logger = logging.getLogger(__name__)

class AgentService:
    """
    Service to handle the full "agent" life cycle that will be performed whenever we prompt it.

    Flow:
      1. Retrieve DataSources for the Project
      2. Retrieve MCP tools for those DataSources
      3. Initialize internal Tools manager
      4. Phase 1 — Diagnosis: refine question, filter DataSources and MCP tools
      5. Re-initialize Tools with filtered DataSources
      6. Build AgentWorkflow (Planning → Research → Synth)
      7. Run workflow and stream events back to the caller
    """

    def __init__(
        self,
        db: AsyncSession,
        mcp_svc: MCPService,
        data_source_svc: DataSourceService,
        chunk_retrieval_svc: ChunkRetrievalService,
    ) -> None:

        self.db = db
        self.mcp_svc = mcp_svc
        self.data_source_svc = data_source_svc
        self.chunk_retrieval_svc = chunk_retrieval_svc


    async def run_agent(
        self,
        llm: LLMBase,
        user_prompt: str,
        conversation_history: list[ChatMessage],
        project_id: UUID,
    ) -> AsyncGenerator[tuple[str, str | dict | None], None]:
        """
        Run the full agentic workflow and stream events back to the caller.

        NOTE: AsyncExitStack is used because we may need multiple MCP servers
        connected simultaneously. Without it, rapid open/close cycles cause
        anyio.BrokenResourceError race conditions.
        """
        async with AsyncExitStack() as async_exit_stack:

            # 1. Retrieve the DataSources associated with the Project
            data_sources: list[DataSource] = await self.data_source_svc.aget_project_data_sources(project_id)
            if not data_sources:
                logger.error("No Data Sources found for Project ID: %s", project_id)
                raise Exception(
                    f"Unable to retrieve context for the provided question — "
                    f"no DataSources are associated with Project: {project_id}"
                )

            # 2. Get MCP tools keyed by data_source_id
            mcp_tools: dict[str, list[FunctionTool]] = await self.mcp_svc.get_mcp_tools(data_sources, async_exit_stack)
            total_mcp = sum(len(t) for t in mcp_tools.values())
            logger.info("Retrieved %d MCP tools across %d DataSources", total_mcp, len(data_sources))

            # 3. Initialize internal tooling manager (all DataSources, pre-Diagnosis)
            tool_manager = Tools(
                data_sources,
                project_id,
                llm,
                self.chunk_retrieval_svc,
            )
            all_internal_tools = tool_manager.get_all_internal_tools()
            logger.info("Initialized %d internal tools across %d DataSources", len(all_internal_tools), len(data_sources))

            # 4. Phase 1: Diagnosis — refine question, filter DataSources and MCP tools
            refined_question, question_type, mcp_tools, data_sources = await self.diagnose_users_question(
                llm, user_prompt, data_sources, all_internal_tools, mcp_tools, conversation_history
            )
            logger.info("Phase 1 Complete: QuestionType=%s, RefinedQuestion='%s'", question_type, refined_question)

            # 5. Re-initialize tool_manager with the filtered DataSources from Diagnosis
            tool_manager = Tools(
                data_sources,
                project_id,
                llm,
                self.chunk_retrieval_svc,
            )

            # 6. Build the Agent Workflow with per-agent tool sets
            token_counter = TokenCountingHandler()
            callback_manager = CallbackManager([token_counter])
            workflow: AgentWorkflow = get_agentic_workflow(
                mcp_tools=mcp_tools,
                llm=llm,
                data_sources=data_sources,
                tool_manager=tool_manager,
                refined_question=refined_question,
                question_type=question_type,
                callback_manager=callback_manager,
            )

            # 7. Run the Agent Workflow
            ctx = Context(workflow)
            handler = workflow.run(
                user_msg=refined_question,
                chat_history=conversation_history,
                ctx=ctx,
                max_iterations=40,
            )

            # 8. Stream events back to the caller
            # TODO: Simplify logging in this flow
            try:
                async for event in handler.stream_events():

                    match event:

                        case AgentStream():
                            # Stream only SynthAgent's final response to the user
                            if event.delta and event.current_agent_name == AgentName.SYNTH:
                                yield format_sse_event(StreamEventType.CHUNK, event.delta), event.delta
                                continue

                            # All other agent activity is internal dialogue — log only
                            if event.delta or event.thinking_delta:
                                logger.debug(
                                    "AgentStreamEvent (%s): Agent=%s, Dialogue=%s, ToolCalls=%d",
                                    "Thinking" if event.thinking_delta else "Delta",
                                    event.current_agent_name,
                                    event.thinking_delta if event.thinking_delta else event.delta,
                                    len(event.tool_calls or []),
                                )

                        case AgentInput():
                            agent_name = event.current_agent_name
                            latest_message = await self._extract_latest_message(event)
                            logger.debug(
                                "AgentInputEvent: Agent=%s, LatestMessage=%s",
                                agent_name,
                                latest_message,
                            )

                        case AgentOutput():
                            agent_name = event.current_agent_name
                            tool_breakdown = []

                            for tool_call in event.tool_calls:
                                tool_name = tool_call.tool_name
                                tool_args = tool_call.tool_kwargs

                                if tool_name == "handoff":
                                    tool_breakdown.append({
                                        "Tool Name": tool_name,
                                        "Handoff To": tool_args.get("to_agent", "unknown"),
                                        "Reason": (tool_args.get("reason", "") or "")[:300],
                                    })
                                else:
                                    tool_breakdown.append({
                                        "Tool Name": tool_name,
                                        "Tool Arguments": tool_args,
                                    })
                            logger.debug("AgentOutputEvent: Agent=%s, Tools=%s", agent_name, tool_breakdown)

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

                        case _:
                            logger.debug("Unknown Event Type: %s", event)

                # Wait for the final result
                result = await handler
                logger.info("Workflow Complete. Result: %s", result)

                # Log plan + accumulated research findings from shared Context
                await self._log_research_state(ctx)

            except Exception as e:
                logger.error("Error in agent workflow: %s", e, exc_info=True)

                error_msg = str(e).lower()
                friendly_msg = "An unexpected error occurred during agent execution."

                if "context_length" in error_msg or "maximum context length" in error_msg:
                    friendly_msg = "Context window exceeded. Please try a shorter prompt or clear conversation history."
                elif "rate_limit" in error_msg or "429" in error_msg:
                    friendly_msg = "Rate limit reached. Please wait a moment before trying again."
                elif "timeout" in error_msg or "deadline exceeded" in error_msg:
                    friendly_msg = "The request timed out. The agent took too long to respond."

                yield format_sse_event(StreamEventType.ERROR, friendly_msg, "Workflow Error"), None
                # Do NOT re-raise — allow token usage to be calculated and returned

            finally:
                yield StreamEventType.TOKEN_USAGE, {
                    # Tokens fed into the LLM (history, system prompts, tool defs, user prompt)
                    "input_tokens": token_counter.prompt_llm_token_count,
                    # Tokens generated by the LLM (responses, tool calls, thinking)
                    "output_tokens": token_counter.completion_llm_token_count,
                    # Combined total
                    "total_tokens": token_counter.total_llm_token_count,
                }


    # ─────────────────────────────────────────────
    # Diagnosis Phase
    # ─────────────────────────────────────────────

    def _extract_summaries(
        self,
        data_sources: list[DataSource],
        internal_tools: list[FunctionTool],
        mcp_tools: dict[str, list[FunctionTool]],
    ) -> tuple[str, str, str]:
        """
        Build string summaries of DataSources, internal tools, and MCP tools
        to pass to the LLM for the Diagnosis phase.
        """
        data_source_info = "\n".join(
            [f"- ID: {ds.id} | Name: {ds.name} | Type: {ds.type} | Provider: {ds.provider}" for ds in data_sources]
        )
        internal_tool_info = "\n".join(
            [f"- {t.metadata.name}: {t.metadata.description}" for t in internal_tools]
        )
        mcp_info_dict = {
            ds_id: [f"{t.metadata.name}: {t.metadata.description}" for t in tools]
            for ds_id, tools in mcp_tools.items()
        }
        mcp_info = json.dumps(mcp_info_dict, indent=2) if mcp_info_dict else "No MCP Tools available."
        return data_source_info, internal_tool_info, mcp_info

    def _format_conversation_history(self, conversation_history: list[ChatMessage], limit: int = 4) -> str:
        """
        Format the last N conversation messages as a plain string to pass to the Diagnosis LLM,
        preventing context bloat from long histories.
        """
        recent_history = conversation_history[-limit:] if conversation_history else []
        history_lines = [
            f"{str(msg.role).replace('MessageRole.', '')}: {msg.content}" for msg in recent_history
        ]
        return "\n".join(history_lines) if history_lines else "No prior conversation history."

    def _filter_mcp_tools(
        self,
        mcp_tools: dict[str, list[FunctionTool]],
        req_mcp_map: dict,
    ) -> dict[str, list[FunctionTool]]:
        """
        Filter the full MCP tool set down to only the tools selected by the Diagnosis phase.

        Args:
            mcp_tools: All MCP tools keyed by data_source_id
            req_mcp_map: Diagnosis output — dict of {data_source_id: [tool_name, ...]}
        """
        filtered: dict[str, list[FunctionTool]] = {}
        for ds_id, tools in mcp_tools.items():
            req_tools_for_ds = req_mcp_map.get(ds_id, [])
            if isinstance(req_tools_for_ds, list):
                filtered[ds_id] = [t for t in tools if t.metadata.name in req_tools_for_ds]
        return filtered

    def _filter_data_sources(
        self,
        data_sources: list[DataSource],
        req_ds_ids: list,
    ) -> list[DataSource]:
        """
        Filter the full DataSource list to only those selected by the Diagnosis phase.
        Falls back to all DataSources if the filtered list would be empty.
        """
        if not req_ds_ids:
            return data_sources
        filtered = [ds for ds in data_sources if str(ds.id) in req_ds_ids]
        return filtered if filtered else data_sources

    async def diagnose_users_question(
        self,
        llm: LLMBase,
        user_prompt: str,
        data_sources: list[DataSource],
        internal_tools: list[FunctionTool],
        mcp_tools: dict[str, list[FunctionTool]],
        conversation_history: list[ChatMessage],
    ) -> tuple[str, str, dict[str, list[FunctionTool]], list[DataSource]]:
        """
        Phase 1: Diagnosis — lightweight LLM call (before the full workflow) that determines:
          a) Which DataSources are relevant to the question
          b) A clarified/refined version of the question
          c) Which MCP tools (if any) are actually needed
          d) The question type/classification

        Returns a tuple of (refined_question, question_type, filtered_mcp_tools, filtered_data_sources).
        """
        logger.info(
            "Executing Phase 1 Diagnosis via %s/%s for prompt: %s",
            llm.provider, llm.model_name, user_prompt,
        )

        data_source_info, internal_tool_info, mcp_info = self._extract_summaries(
            data_sources, internal_tools, mcp_tools
        )
        conversation_history_str = self._format_conversation_history(conversation_history)

        diagnosis = await llm.diagnose_question(
            user_prompt, data_source_info, internal_tool_info, mcp_info, conversation_history_str
        )
        logger.info("Diagnosis Result: %s", diagnosis)

        refined_question = diagnosis.get("refined_question", user_prompt)
        question_type = diagnosis.get("question_type", "General Inquiry")

        mcp_tools = self._filter_mcp_tools(mcp_tools, diagnosis.get("required_mcp_tools", {}))
        data_sources = self._filter_data_sources(data_sources, diagnosis.get("required_data_sources", []))

        return refined_question, question_type, mcp_tools, data_sources


    # ─────────────────────────────────────────────
    # Helper / Debug Utilities
    # ─────────────────────────────────────────────

    async def _extract_latest_message(self, event: AgentInput) -> dict:
        """
        Extract the most recent message from an AgentInput event for debug logging.
        """
        latest_input = event.input[-1] if event.input else None
        if not latest_input:
            raise Exception("No input messages available: Agent in corrupt state")

        latest_message_text = "".join(
            block.text for block in latest_input.blocks if isinstance(block, TextBlock)
        )
        return {"message": latest_message_text, "role": latest_input.role}

    async def _log_research_state(self, ctx: Context) -> None:
        """
        Read and log the research plan, plan revision history, and all accumulated findings
        from the shared Context store. Called after the workflow completes.
        """
        try:
            store = ctx.store
            plan: str | None = await store.get("plan", None)  # type: ignore[arg-type]
            plan_history: list = await store.get("plan_history", [])  # type: ignore[arg-type]
            findings: list = await store.get("findings", [])  # type: ignore[arg-type]

            if plan:
                logger.info("=== RESEARCH PLAN (final) ===")
                logger.info(plan)
                if len(plan_history) > 1:
                    logger.info("Plan was revised %d time(s) during research", len(plan_history) - 1)
            else:
                logger.info("Research State — no plan was written to shared state.")

            if findings:
                logger.info("=== RESEARCH FINDINGS (%d total) ===", len(findings))
                for i, f in enumerate(findings, 1):
                    logger.info(
                        "  [%d] DS=%s | %s: %s",
                        i,
                        f.get("data_source_id", "unknown"),
                        f.get("source", "unknown source"),
                        f.get("finding", "no summary"),
                    )
            else:
                logger.info("Research State — no findings were recorded in shared state.")

        except Exception as state_err:
            logger.warning("Could not read research state from Context: %s", state_err)
