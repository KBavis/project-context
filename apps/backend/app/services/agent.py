from uuid import UUID
from contextlib import AsyncExitStack
from typing import AsyncGenerator, TYPE_CHECKING
import asyncio
import logging
import json
import re

import openai

from llama_index.core.base.llms.types import TextBlock
from workflows.context.context import Context
from app.pydantic.streaming import StreamEventType
from app.services.util import format_sse_event
from app.core import settings
from sqlalchemy.ext.asyncio import AsyncSession

from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from llama_index.core.memory import ChatMemoryBuffer
from app.agents import Tools, get_agentic_workflow, build_answer_prompt
from app.llm import LLMBase
from app.services.mcp import MCPService
from app.services.data_source import DataSourceService
from app.services.chunk_retrieval import ChunkRetrievalService
from app.services.repository_changes import RepositoryChangesService
from app.models.data_source import DataSource, DataSourceType
from app.data_providers.ingestible.base import IngestibleDataProvider

from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import (AgentOutput, ToolCallResult, AgentWorkflow, AgentInput)
from llama_index.core.llms import ChatMessage

if TYPE_CHECKING:
    from app.models.project import Project

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
        repo_changes_svc: RepositoryChangesService | None = None,
    ) -> None:

        self.db = db
        self.mcp_svc = mcp_svc
        self.data_source_svc = data_source_svc
        self.chunk_retrieval_svc = chunk_retrieval_svc
        self.repo_changes_svc = repo_changes_svc


    async def run_agent(
        self,
        llm: LLMBase,
        user_prompt: str,
        conversation_history: list[ChatMessage],
        project_id: UUID,
        project: "Project | None" = None,
        lightweight_llm: LLMBase | None = None,
    ) -> AsyncGenerator[tuple[str, str | dict | None], None]:
        """
        Run the full agentic workflow and stream events back to the caller.

        NOTE: AsyncExitStack is used because we may need multiple MCP servers
        connected simultaneously. Without it, rapid open/close cycles cause
        anyio.BrokenResourceError race conditions.
        """
        async with AsyncExitStack() as async_exit_stack:

            # ─────────────────────────────────────────────
            # Setup: resolve data sources, tooling, and MCP tools for this run
            # ─────────────────────────────────────────────
            data_sources: list[DataSource] = await self.data_source_svc.aget_project_data_sources(project_id)
            if not data_sources:
                logger.error("No Data Sources found for Project ID: %s", project_id)
                raise Exception(
                    f"Unable to retrieve context for the provided question — "
                    f"no DataSources are associated with Project: {project_id}"
                )

            # Warm the BM25 index in the background so it's ready by ChunkRetrieval time.
            asyncio.create_task(self._warm_bm25_cache(project_id))

            # Project summary so every phase knows *which* project it is assisting with.
            project_context = self._build_project_context(project)

            mcp_tools: dict[str, list[FunctionTool]] = await self.mcp_svc.get_mcp_tools(data_sources, async_exit_stack)
            logger.info("Retrieved %d MCP tools across %d DataSources", sum(len(t) for t in mcp_tools.values()), len(data_sources))

            scope_map = {}
            if self.repo_changes_svc:
                scope_map = await self.repo_changes_svc.build_scoped_repository_file_id_map(project_id)

            tool_manager = Tools(
                data_sources=data_sources,
                project_id=project_id,
                llm=llm,
                chunk_retrieval_svc=self.chunk_retrieval_svc,
                data_source_svc=self.data_source_svc,
                scope_map=scope_map,
                repo_changes_svc=self.repo_changes_svc,
            )

            # Token counting spans the research + answer LLM calls.
            token_counter = TokenCountingHandler()
            callback_manager = CallbackManager([token_counter])

            # ─────────────────────────────────────────────
            # Phase 1: Diagnosis (uses lightweight LLM for speed/cost)
            # Refine the question, classify research depth, and filter MCP tools down to
            # only what's needed — before any expensive research begins.
            # ─────────────────────────────────────────────
            diag_llm = lightweight_llm or llm
            refined_question, question_type, research_depth, mcp_tools = await self.diagnose_users_question(
                diag_llm, user_prompt, data_sources, tool_manager.get_all_internal_tools(), mcp_tools,
                conversation_history, project_context=project_context,
            )
            logger.info(
                "Phase 1 (Diagnosis) complete: question_type=%s, research_depth=%s, refined_question='%s'",
                question_type, research_depth, refined_question,
            )
            scope_summary = await self._build_project_scope_summary(project_id, data_sources)

            # ─────────────────────────────────────────────
            # Phase 2: Research
            # A single self-planning agent investigates the data sources and logs findings
            # to shared state, bounded by a depth-derived iteration budget and a
            # token-limited memory so context can't grow without bound.
            # ─────────────────────────────────────────────
            workflow: AgentWorkflow = get_agentic_workflow(
                mcp_tools=mcp_tools,
                llm=llm,
                data_sources=data_sources,
                tool_manager=tool_manager,
                refined_question=refined_question,
                question_type=question_type,
                research_depth=research_depth,
                scope_summary=scope_summary,
                project_context=project_context,
                callback_manager=callback_manager,
            )
            ctx = Context(workflow)
            memory = ChatMemoryBuffer.from_defaults(
                chat_history=conversation_history,
                token_limit=settings.AGENT_MEMORY_TOKEN_LIMIT,
            )

            try:
                # stream research events (tool calls, status updates) to the caller
                async for event in self._run_research(
                    workflow, ctx, refined_question, memory, self._research_budget(research_depth)
                ):
                    yield event

                # ─────────────────────────────────────────────
                # Phase 3: Stream Response
                # Resolve deterministic citations from the findings, build the
                # Constitution-governed answer prompt, and stream the answer to the user.
                # ─────────────────────────────────────────────
                async for event in self._stream_response(
                    llm, tool_manager, ctx, refined_question, project_context, scope_summary, callback_manager
                ):
                    yield event

            finally:
                # Always report token usage, even if a phase failed mid-flight.
                yield StreamEventType.TOKEN_USAGE, {
                    # Tokens fed into the LLM (history, system prompts, tool defs, user prompt)
                    "input_tokens": token_counter.prompt_llm_token_count,
                    # Tokens generated by the LLM (responses, tool calls, thinking)
                    "output_tokens": token_counter.completion_llm_token_count,
                    # Combined total
                    "total_tokens": token_counter.total_llm_token_count,
                }


    async def _run_research(
        self,
        workflow: AgentWorkflow,
        ctx: Context,
        refined_question: str,
        memory: ChatMemoryBuffer,
        max_iterations: int,
    ) -> AsyncGenerator[tuple[str, str | dict | None], None]:
        """
        Phase 2: run the bounded research loop, streaming lightweight status events.

        The agent logs findings into `ctx.store` via its tools. If the loop hits its
        iteration budget (rather than finishing naturally), we record
        `ctx.store['research_truncated'] = True` so the answer phase can note the answer
        may be partial. Errors are swallowed so we still answer from partial findings.
        """
        truncated = False
        try:
            yield format_sse_event(StreamEventType.STATUS, "Researching your question...", "Researching"), None
            handler = workflow.run(
                user_msg=refined_question,
                memory=memory,
                ctx=ctx,
                max_iterations=max_iterations,
            )

            async for event in handler.stream_events():
                match event:
                    case AgentInput():
                        # Research turns are internal; surface a lightweight status only.
                        yield format_sse_event(StreamEventType.STATUS, "Researching your question..."), None
                    case AgentOutput():
                        for tool_call in event.tool_calls:
                            logger.info("[Research] Tool Call: %s (Args: %s)", tool_call.tool_name, str(tool_call.tool_kwargs)[:150])
                            yield format_sse_event(StreamEventType.STATUS, f"Running {tool_call.tool_name}..."), None
                    case ToolCallResult():
                        self._log_tool_result(event)
                    case _:
                        pass

            # The research agent's own terminal text is discarded — findings drive the answer.
            await handler

        except Exception as research_err:
            # Budget exhaustion or a mid-loop failure must NOT abort the response; we answer
            # from whatever findings were gathered so far (graceful degradation).
            err_text = str(research_err).lower()
            truncated = "max iteration" in err_text or "maximum iteration" in err_text
            logger.warning("Research phase ended early (answering from findings gathered so far): %s", research_err)

        await self._log_research_state(ctx)
        await ctx.store.set("research_truncated", truncated)

    def _log_tool_result(self, event: ToolCallResult) -> None:
        """Log a tool result at the appropriate level (error / no-data / ok) for observability."""
        output_str = str(event.tool_output)
        output_len = len(output_str)
        is_error = getattr(event.tool_output, "is_error", False)

        if is_error or (output_len < 100 and "error" in output_str.lower()):
            logger.warning("[Tool Result] %s FAILED or returned error: %s", event.tool_name, output_str[:150].replace('\n', ' '))
        elif output_len == 0 or output_str.strip() in ["None", "[]", "{}", ""]:
            logger.warning("[Tool Result] %s returned NO DATA.", event.tool_name)
        else:
            logger.info("[Tool Result] %s: returned %s characters of data.", event.tool_name, output_len)

    async def _stream_response(
        self,
        llm: LLMBase,
        tool_manager: Tools,
        ctx: Context,
        refined_question: str,
        project_context: str,
        scope_summary: str,
        callback_manager: CallbackManager,
    ) -> AsyncGenerator[tuple[str, str | dict | None], None]:
        """
        Phase 3: resolve deterministic citations and stream the Constitution-governed answer.

        Reads the accumulated findings (and the research_truncated flag) from `ctx.store`,
        resolves citations in code, builds the answer prompt, and streams the answer. Emits
        the citation map as a final event. Answer-time errors surface as a friendly message
        rather than being raised, so the caller can still report token usage.

        Rate Limit Strategy (429's):
            Retry the entire ``astream_complete`` call with exponential backoff,
            honouring the ``Retry-After`` header when present.
        """
        try:
            findings: list = await ctx.store.get("findings", [])  # type: ignore[arg-type]
        except Exception:
            findings = []
        try:
            research_truncated: bool = await ctx.store.get("research_truncated", False)  # type: ignore[arg-type]
        except Exception:
            research_truncated = False
        try:
            file_line_counts: dict = await ctx.store.get("file_line_counts", {})  # type: ignore[arg-type]
        except Exception:
            file_line_counts = {}

        try:
            citation_map = await self._build_citation_map(findings, tool_manager, file_line_counts)

            yield format_sse_event(StreamEventType.STATUS, "Composing answer...", "Answering"), None

            answer_prompt = build_answer_prompt(
                refined_question=refined_question,
                project_context=project_context,
                scope_summary=scope_summary,
                findings=findings,
            )

            answer_llm = llm.get_llama_idx_instance(callback_manager=callback_manager)

            # invoke astream_complete with rate-limit retry logic
            response_stream = await self._astream_complete_with_retry(answer_llm, answer_prompt)

            async for chunk in response_stream:
                delta = getattr(chunk, "delta", None) or ""
                if delta:
                    yield format_sse_event(StreamEventType.CHUNK, delta), delta

            # inform user if research was cut shorted by backstop
            if research_truncated:
                note = (
                    "\n\n---\n\n_This answer is based on the most relevant sources I found within my "
                    "research budget for this question. If it doesn't fully cover what you need, ask a "
                    "more specific follow-up and I'll focus there._"
                )
                yield format_sse_event(StreamEventType.CHUNK, note), note

            # Emit the citation map so the client can render inline cite:<id> links + footer.
            yield StreamEventType.CITATIONS, citation_map

        except Exception as e:
            logger.error("Error composing answer: %s", e, exc_info=True)

            error_msg = str(e).lower()
            friendly_msg = "An unexpected error occurred while composing the answer."

            if "context_length" in error_msg or "maximum context length" in error_msg:
                friendly_msg = "Context window exceeded. Please try a shorter prompt or clear conversation history."
            elif "rate_limit" in error_msg or "429" in error_msg:
                friendly_msg = "Rate limit reached. Please wait a moment before trying again."
            elif "timeout" in error_msg or "deadline exceeded" in error_msg:
                friendly_msg = "The request timed out. The agent took too long to respond."

            yield format_sse_event(StreamEventType.ERROR, friendly_msg, "Answer Error"), None

    async def _astream_complete_with_retry(self, llm, prompt: str, max_retries: int = 4):
        """
        Call ``llm.astream_complete`` with exponential backoff on rate-limit errors 
        and honors the ``Retry-After`` header when present.
        """
        base_delay = 1.0           # seconds; doubles each attempt (1, 2, 4, 8)
        max_delay = 30.0           # cap per-retry wait
        max_retry_after = 120.0    # cap for server-specified Retry-After
        last_err: openai.RateLimitError | None = None

        for attempt in range(1, max_retries + 1):
            try:
                return await llm.astream_complete(prompt)
            except openai.RateLimitError as e:
                last_err = e
                if attempt >= max_retries:
                    raise

                # Honour Retry-After header; fall back to exponential backoff.
                wait = min(base_delay * (2 ** (attempt - 1)), max_delay)
                retry_after = self._parse_retry_after_header(e)
                if retry_after is not None:
                    wait = min(retry_after, max_retry_after)

                logger.warning(
                    "Rate-limited on astream_complete (attempt %d/%d). "
                    "Retrying in %.1fs... [Retry-After=%s]",
                    attempt, max_retries, wait,
                    f"{retry_after:.1f}s" if retry_after is not None else "absent",
                )
                await asyncio.sleep(wait)

        # Should never reach here, but satisfy type-checkers.
        raise last_err  # type: ignore[misc]

    # ─────────────────────────────────────────────
    # Citation Resolution (deterministic, code-side — NOT an agent tool)
    # ─────────────────────────────────────────────

    async def _build_citation_map(
        self, findings: list[dict], tool_manager: Tools, file_line_counts: dict
    ) -> dict[str, dict]:
        """
        Resolve every research finding into a citation entry, keyed by a stable 1-based
        finding id (as a string). The answer LLM references these ids via `cite:<id>`
        markers; the frontend renders them from this map. The 1-based ids must match the
        numbering used by build_answer_prompt's finding list.

        Each entry: {url, label, data_source_id, data_source_name, data_source_url}.
        Findings that can't be resolved (unknown DataSource, provider error, or an
        [UNANSWERABLE] marker) are skipped. DataSource rows come from the run's data sources
        and providers are built here; `file_line_counts` (recorded by the view_file tool into
        shared state) lets us drop the anchor when a range spans the whole file.
        """
        ds_by_id = {ds.id: ds for ds in tool_manager.data_sources}
        providers: dict[UUID, IngestibleDataProvider] = {}

        citation_map: dict[str, dict] = {}
        for idx, finding in enumerate(findings, start=1):
            source = str(finding.get("source", "")).strip()
            ds_id_raw = finding.get("data_source_id")
            if not source or not ds_id_raw or source.startswith("[UNANSWERABLE]"):
                continue
            try:
                ds_uuid = UUID(str(ds_id_raw))
            except (ValueError, TypeError):
                logger.warning("Skipping citation for finding %d: invalid data_source_id=%r", idx, ds_id_raw)
                continue

            ds = ds_by_id.get(ds_uuid)
            if ds is None:
                logger.warning("Skipping citation for finding %d: unknown data_source_id=%s", idx, ds_uuid)
                continue

            provider = providers.get(ds_uuid)
            if provider is None:
                try:
                    provider = IngestibleDataProvider.from_provider(ds)
                except Exception as e:
                    logger.warning("Skipping citation for finding %d: cannot build provider for %s: %s", idx, ds_uuid, e)
                    continue
                providers[ds_uuid] = provider

            file_path, line_range = self._parse_source(source)
            try:
                base_markdown = await provider.generate_citation(file_path)
            except Exception as e:
                logger.warning("Skipping citation for finding %d (%s): %s", idx, file_path, e)
                continue

            label, url = self._parse_markdown_link(base_markdown, fallback_label=file_path)

            # Append a line anchor for repository sources when a line range is known — but
            # skip it when the range spans the whole file (a file-level link reads cleaner).
            if line_range and ds.type == DataSourceType.REPOSITORY:
                start, end = line_range
                total = file_line_counts.get(f"{ds_uuid}::{file_path.lstrip('/')}")
                covers_whole_file = total is not None and start <= 1 and end >= total
                if not covers_whole_file:
                    url = f"{url}{provider.line_anchor(start, end)}"
                    label = f"{file_path}:{start}-{end}"

            citation_map[str(idx)] = {
                "url": url,
                "label": label,
                "data_source_id": str(ds_uuid),
                "data_source_name": ds.name,
                "data_source_url": ds.url,
            }
        return citation_map

    @staticmethod
    def _parse_source(source: str) -> tuple[str, tuple[int, int] | None]:
        """
        Split a finding `source` into (file_path, (start, end)).

        Handles 'path/to/file.py:45-62' and 'path:45'. If the source carries multiple
        disjoint ranges (e.g. 'file.py:704-721,768-785'), only the FIRST contiguous range
        is used — a single citation link cannot express disjoint ranges. Returns
        (source, None) when no range is present.
        """
        m = re.match(r"^(?P<path>.+?):(?P<lines>\d[\d\s,\-]*)$", source)
        if not m:
            return source, None
        first = re.match(r"(\d+)(?:-(\d+))?", m.group("lines").strip())
        if not first:
            return m.group("path"), None
        start = int(first.group(1))
        end = int(first.group(2)) if first.group(2) else start
        return m.group("path"), (start, end)

    @staticmethod
    def _parse_markdown_link(markdown: str, fallback_label: str) -> tuple[str, str]:
        """
        Extract (label, url) from a provider's `[label](url)` citation string.
        Falls back to (fallback_label, stripped markdown) if the pattern doesn't match.
        """
        m = re.match(r"^\s*\[(?P<label>.*?)\]\((?P<url>.*?)\)\s*$", markdown, re.DOTALL)
        if not m:
            return fallback_label, markdown.strip()
        return (m.group("label") or fallback_label), m.group("url")

    def _research_budget(self, research_depth: str) -> int:
        """
        Map the diagnosis research_depth to an iteration budget (a CEILING, not a target).

        The agent's convergence rule stops it early once new searches surface nothing new,
        so an over-classified question doesn't waste iterations; an under-classified one is
        covered by the 'keep searching' backstop. Default (standard) on anything unknown.
        """
        depth = (research_depth or "standard").lower()
        if depth == "shallow":
            return settings.AGENT_RESEARCH_MAX_ITERATIONS_SIMPLE
        if depth == "deep":
            return settings.AGENT_RESEARCH_MAX_ITERATIONS_DEEP
        return settings.AGENT_RESEARCH_MAX_ITERATIONS

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

    def _build_project_context(self, project: "Project | None") -> str:
        """
        Build a human-readable summary of the Project the agent is assisting with, so every
        phase understands *which* project it is interfacing with (name, description, scope)
        rather than only its data sources. Prevents the agent from being confused when the
        user refers to 'this project' or the project by name.
        """
        if not project:
            return "No project metadata is available."

        lines = [f"**Project:** {project.project_name}"]
        if getattr(project, 'description', None):
            lines.append(f"**Description:** {project.description}")
        if getattr(project, 'lob', None):
            lines.append(f"**Line of Business:** {project.lob}")
        if getattr(project, 'parent_issues', None):
            lines.append(f"**Parent Issues:** {', '.join(project.parent_issues)}")
        return '\n'.join(lines)

    async def _build_project_scope_summary(self, project_id: UUID, data_sources: list[DataSource]) -> str:
        """
        Builds a summary of the project scope for Data Sources that are scoped by issues.
        """
        if not self.repo_changes_svc:
            return ""
            
        scope_summary = ""
        for ds in data_sources:
            if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues:
                changes = await self.repo_changes_svc.get_project_repo_summary(project_id, ds.id)
                if changes:
                    file_diffs = await self.repo_changes_svc.get_file_diffs(project_id, ds.id)
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
        project_context: str = "",
    ) -> tuple[str, str, str, dict[str, list[FunctionTool]]]:
        """
        Phase 1: Diagnosis — lightweight LLM call (before the full workflow) that determines:
          a) A clarified/refined version of the question
          b) Which MCP tools (if any) are actually needed
          c) The question type/classification
          d) The research depth (shallow | standard | deep) used to size the iteration budget

        Returns a tuple of (refined_question, question_type, research_depth, filtered_mcp_tools).
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
            user_prompt, data_source_info, internal_tool_info, mcp_info, conversation_history_str,
            project_context=project_context,
        )
        logger.info("Diagnosis Result: %s", diagnosis)

        refined_question = diagnosis.get("refined_question", user_prompt)
        question_type = diagnosis.get("question_type", "General Inquiry")
        research_depth = str(diagnosis.get("research_depth", "standard")).lower()
        if research_depth not in ("shallow", "standard", "deep"):
            research_depth = "standard"

        mcp_tools = self._filter_mcp_tools(mcp_tools, diagnosis.get("required_mcp_tools", {}))

        return refined_question, question_type, research_depth, mcp_tools


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


    @staticmethod
    def _parse_retry_after_header(exc: openai.RateLimitError) -> float | None:
        """
        Extract the ``Retry-After`` value (in seconds) from a RateLimitError.
        """
        response = getattr(exc, "response", None)
        if response is None:
            return None
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        raw = headers.get("retry-after")  # httpx.Headers is case-insensitive
        if raw is None:
            return None
        try:
            value = float(raw)
        except (ValueError, TypeError):
            return None
        return value if value > 0 else None