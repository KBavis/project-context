from uuid import UUID
from contextlib import AsyncExitStack
from typing import AsyncGenerator
import asyncio
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
from app.services.diff import DiffService
from app.models.data_source import DataSource, DataSourceType

from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (AgentOutput, AgentStream, ToolCallResult, AgentWorkflow, AgentInput)
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
        diff_svc: DiffService | None = None,
    ) -> None:

        self.db = db
        self.mcp_svc = mcp_svc
        self.data_source_svc = data_source_svc
        self.chunk_retrieval_svc = chunk_retrieval_svc
        self.diff_svc = diff_svc


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

            # 1b. Kick off the BM25 index build in the background so its ready by ChunkRetrieval time
            asyncio.create_task(self._warm_bm25_cache(project_id))

            # 2. Get MCP tools keyed by data_source_id
            mcp_tools: dict[str, list[FunctionTool]] = await self.mcp_svc.get_mcp_tools(data_sources, async_exit_stack)
            total_mcp = sum(len(t) for t in mcp_tools.values())
            logger.info("Retrieved %d MCP tools across %d DataSources", total_mcp, len(data_sources))

            # 3. Initialize internal tooling manager (all DataSources, pre-Diagnosis)
            scope_map = {}
            if self.diff_svc:
                scope_map = await self.diff_svc.build_scoped_repository_file_id_map(project_id)

            tool_manager = Tools(
                data_sources=data_sources,
                project_id=project_id,
                llm=llm,
                chunk_retrieval_svc=self.chunk_retrieval_svc,
                data_source_svc=self.data_source_svc,
                scope_map=scope_map,
                diff_svc=self.diff_svc,
            )
            all_internal_tools = tool_manager.get_all_internal_tools()
            logger.info("Initialized %d internal tools across %d DataSources", len(all_internal_tools), len(data_sources))

            # 4. Phase 1: Diagnosis — refine question and filter MCP tools
            refined_question, question_type, mcp_tools = await self.diagnose_users_question(
                llm, user_prompt, data_sources, all_internal_tools, mcp_tools, conversation_history
            )
            logger.info("Phase 1 Complete: QuestionType=%s, RefinedQuestion='%s'", question_type, refined_question)

            # 5. Inject scope context
            scope_summary = await self._build_project_scope_summary(project_id, data_sources)

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
                scope_summary=scope_summary,
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
            try:
                seen_agents = set()
                async for event in handler.stream_events():

                    match event:

                        case AgentStream():
                            # Stream only SynthAgent's final response to the user
                            if event.delta and event.current_agent_name == AgentName.SYNTH:
                                yield format_sse_event(StreamEventType.CHUNK, event.delta), event.delta
                                continue

                            # All other agent activity is internal dialogue — ignore token-by-token logging to reduce clutter.
                            pass

                        case AgentInput():
                            agent_name = event.current_agent_name
                            phase_name = agent_name.replace("Agent", "")
                            if phase_name not in seen_agents:
                                seen_agents.add(phase_name)
                                logger.info("\n=== [%s Phase Started] ===", phase_name.upper())
                            yield format_sse_event(StreamEventType.STATUS, f"{agent_name} is thinking..."), None

                        case AgentOutput():
                            agent_name = event.current_agent_name

                            for tool_call in event.tool_calls:
                                tool_name = tool_call.tool_name
                                tool_args = tool_call.tool_kwargs

                                if tool_name == "handoff":
                                    handoff_to = tool_args.get("to_agent", "unknown").replace("Agent", "")
                                    reason = str(tool_args.get("reason", ""))[:150]
                                    logger.info("[%s Agent] Handoff -> %s Agent (Reason: %s)", agent_name, handoff_to, reason)
                                    yield format_sse_event(StreamEventType.STATUS, f"Handing off to {handoff_to}..."), None
                                else:
                                    logger.info("[%s Agent] Tool Call: %s (Args: %s)", agent_name, tool_name, str(tool_args)[:150])
                                    yield format_sse_event(StreamEventType.STATUS, f"{agent_name} running tool: {tool_name}..."), None

                        case ToolCallResult():
                            output_str = str(event.tool_output)
                            output_len = len(output_str)

                            # Check for explicit errors or empty responses
                            is_error = getattr(event.tool_output, "is_error", False)
                            
                            if is_error or (output_len < 100 and "error" in output_str.lower()):
                                error_msg = output_str[:150].replace('\n', ' ')
                                logger.warning("[Tool Result] %s FAILED or returned error: %s", event.tool_name, error_msg)
                            
                            elif output_len == 0 or output_str.strip() in ["None", "[]", "{}", ""]:
                                logger.warning("[Tool Result] %s returned NO DATA.", event.tool_name)
                                
                            else:
                                logger.info("[Tool Result] %s: returned %s characters of data.", event.tool_name, output_len)

                        case _:
                            pass

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


    async def _warm_bm25_cache(self, project_id: UUID) -> None:
        """
        Resolve the project's searchable data sources and pre-build the BM25 index for them.

        Runs as a fire-and-forget background task. We resolve the ids and warm only the 
        unscoped data sources (scoped repositories are not cached, so warming them is wasted work).
        """
        try:
            data_sources = await self.data_source_svc.aget_project_data_sources(project_id)
            unscoped_ds_ids = [
                str(ds.id) for ds in data_sources
                if not (ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues)
            ]
            await self.chunk_retrieval_svc.warm_bm25_cache(unscoped_ds_ids)
        except Exception as e:
            logger.warning("BM25 warmup task failed for Project %s: %s", project_id, e)


    # ─────────────────────────────────────────────
    # Diagnosis Phase
    # ─────────────────────────────────────────────

    async def _build_project_scope_summary(self, project_id: UUID, data_sources: list[DataSource]) -> str:
        """
        Builds a summary of the project scope for Data Sources that are scoped by issues.
        """
        if not self.diff_svc:
            return ""
            
        scope_summary = ""
        for ds in data_sources:
            if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues:
                changes = await self.diff_svc.get_project_repo_summary(project_id, ds.id)
                if changes:
                    file_diffs = await self.diff_svc.get_file_diffs(project_id, ds.id)
                    if file_diffs:
                        if not scope_summary:
                            scope_summary = (
                                "## Project Scope Summary\n"
                                "The following sections provide a high-level overview of the specific code changes "
                                "introduced to each repository data source as a result of this Project. This provides "
                                "the \"grounding\" of what this Project is about.\n\n"
                            )

                        files_touched = len(file_diffs)
                        last_synced = changes.last_synced_time.strftime("%Y-%m-%d") if changes.last_synced_time else "Never"
                        
                        scope_summary += f"### Project Scope in {ds.name}\n"
                        scope_summary += f"Files touched: {files_touched} | Last synced: {last_synced}\n"
                        scope_summary += "Changes:\n"
                        for fd in file_diffs:
                            scope_summary += f"- {fd.file_path} ({fd.change_type.value})\n"
                        scope_summary += "\n"
        return scope_summary

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
        ds_infos = []
        for ds in data_sources:
            info = f"- ID: {ds.id} | Name: {ds.name} | Type: {ds.type} | Provider: {ds.provider}"
            ds_infos.append(info)
        data_source_info = "\n".join(ds_infos)
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



    async def diagnose_users_question(
        self,
        llm: LLMBase,
        user_prompt: str,
        data_sources: list[DataSource],
        internal_tools: list[FunctionTool],
        mcp_tools: dict[str, list[FunctionTool]],
        conversation_history: list[ChatMessage],
    ) -> tuple[str, str, dict[str, list[FunctionTool]]]:
        """
        Phase 1: Diagnosis — lightweight LLM call (before the full workflow) that determines:
          a) A clarified/refined version of the question
          b) Which MCP tools (if any) are actually needed
          c) The question type/classification

        Returns a tuple of (refined_question, question_type, filtered_mcp_tools).
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

        return refined_question, question_type, mcp_tools


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
