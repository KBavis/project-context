from collections import defaultdict
from llama_index.core.tools import FunctionTool
from uuid import UUID
from typing import Callable, Any
import re

from workflows.context.context import Context

from app.llm import LLMBase
from app.models.data_source import DataSource, DataSourceType
from app.services.chunk_retrieval import ChunkRetrievalService
from app.services.data_source import DataSourceService
from app.services.diff import DiffService
from app.data_providers.ingestible.base import IngestibleDataProvider

import logging
logger = logging.getLogger(__name__)


class Tools:
    """
    Manages all internal tooling available during an Agentic Workflow execution.

    Tools are organized into three purpose-built sets, one per agent phase:
      - Planning:  semantic_search, list_directory, write_plan
      - Research:  view_file, list_directory, grep_search, update_research_state, write_plan + MCP tools
      - Synthesis: generate_citation (per DataSource)

    Per-DataSource tools are named with a unique slug (first 8 hex chars of the DS UUID)
    so the LLM can unambiguously select the right tool for the right data source.
    """

    def __init__(
        self,
        data_sources: list[DataSource],
        project_id: UUID,
        llm: LLMBase,
        chunk_retrieval_svc: ChunkRetrievalService,
        data_source_svc: DataSourceService,
        data_source_file_ids: dict[str, list[str]],
        diff_svc: DiffService | None = None,
    ):
        self.data_sources = data_sources
        self.project_id = project_id
        self.llm = llm
        self.chunk_retrieval_svc = chunk_retrieval_svc
        self.data_source_svc = data_source_svc
        self.diff_svc = diff_svc
        # data_source_file_ids restricts search queries for issue-scoped repos
        self.data_source_file_ids = data_source_file_ids

        # Per-DataSource tool buckets (keyed by DS id)
        self._ds_view_file_tools: dict[UUID, FunctionTool] = {}
        self._ds_list_dir_tools: dict[UUID, FunctionTool] = {}
        self._ds_citation_tools: dict[UUID, FunctionTool] = {}

        # Project-wide tools (initialized as None, set in _init_tooling)
        self._semantic_search_tool: FunctionTool
        self._grep_search_tool: FunctionTool
        self._update_research_state_tool: FunctionTool
        self._write_plan_tool: FunctionTool

        # DataSource's of type REPOSITORY configured for this Project that are `scoped_by_issues`
        self._scoped_repo_data_sources: list[DataSource] = [
            ds for ds in data_sources
            if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues
        ]

        # Conditionally built tool for extracting file diffs across scoped repositories
        self._get_file_diff_tool: FunctionTool | None = None

        self._init_tooling()


    # ─────────────────────────────────────────────
    # Public: Per-Agent Tool Sets
    # ─────────────────────────────────────────────

    def get_planning_tools(self) -> list[FunctionTool]:
        """
        Tools for the PlanningAgent:
          - semantic_search (find conceptual starting points)
          - list_directory_* (one per DataSource, explore structure)
          - write_plan (commit plan to shared state)
        """
        return [
            self._semantic_search_tool,
            self._grep_search_tool,
            self._write_plan_tool,
            *self._ds_list_dir_tools.values(),
        ]

    def get_research_tools(self, mcp_tools: dict[str, list[FunctionTool]]) -> list[FunctionTool]:
        """
        Tools for the ResearchAgent:
          - view_file_* (read full file contents, one per DataSource)
          - list_directory_* (navigate structure, one per DataSource)
          - semantic_search (find conceptually related files when stuck or pivoting)
          - grep_search (exact keyword / regex matching)
          - update_research_state (log findings to shared scratchpad)
          - write_plan (revise plan when new discoveries change direction)
          - get_file_diff (when scoped repositories exist)
          - All MCP tools for the relevant DataSources
        """
        tools: list[FunctionTool] = [
            self._semantic_search_tool,
            self._grep_search_tool,
            self._update_research_state_tool,
            self._write_plan_tool,
            *self._ds_view_file_tools.values(),
            *self._ds_list_dir_tools.values(),
        ]
        if self._get_file_diff_tool:
            tools.append(self._get_file_diff_tool)
        for ds_tools in mcp_tools.values():
            tools.extend(ds_tools)
        return tools

    def get_synthesis_tools(self) -> list[FunctionTool]:
        """
        Tools for the SynthesisAgent:
          - generate_citation_* (one per DataSource, produces formatted markdown citations)
        """
        return list(self._ds_citation_tools.values())

    def get_all_internal_tools(self) -> list[FunctionTool]:
        """
        Returns all unique internal tools across all agent phases.
        Used by the Diagnosis phase to summarize available tooling for the LLM.
        """
        tools = [
            self._semantic_search_tool,
            self._grep_search_tool,
            self._update_research_state_tool,
            self._write_plan_tool,
            *self._ds_view_file_tools.values(),
            *self._ds_list_dir_tools.values(),
            *self._ds_citation_tools.values(),
        ]
        if self._get_file_diff_tool:
            tools.append(self._get_file_diff_tool)
        return tools


    # ─────────────────────────────────────────────
    # Private: Tooling Initialization
    # ─────────────────────────────────────────────

    def _ds_slug(self, ds: DataSource) -> str:
        """
        Derive a human-readable slug from the DataSource name for use as a tool name suffix.
        Example: "Backend Repo" → "backend_repo", "Confluence Wiki" → "confluence_wiki"
        """
        slug = ds.name.lower()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)  # replace non-alphanumeric runs with _
        slug = slug.strip("_")                     # remove leading/trailing underscores
        return slug[:30]                            # cap length to keep tool names manageable

    def _init_tooling(self):
        """
        Initialize all internal tools. Per-DataSource tools are built once per provider
        and stored in type-separated dicts for easy retrieval by agent phase.
        """

        # Step 1: Per-DataSource tools (view_file, list_directory, generate_citation)
        for ds in self.data_sources:
            try:
                provider = IngestibleDataProvider.from_provider(ds)
            except Exception as e:
                logger.info(
                    f"Skipping tool creation for DataSource={ds.id}: "
                    f"type={ds.type} is not ingestible. Reason: {e}"
                )
                continue
            slug = self._ds_slug(ds)

            self._ds_view_file_tools[ds.id] = self._build_function_tool(
                async_fn=self._make_view_file_fn(ds, provider),
                function_name=f"view_file_{slug}",
                description=(
                    f"View the full contents of a file in DataSource '{ds.name}' ({ds.type}: {ds.provider}). "
                    "For standard text and code files, this retrieves their contents directly. "
                    "For PDF files (.pdf), this automatically retrieves the parsed plain text chunks sequentially from our document store, avoiding binary file downloads. "
                    "The file_path argument must NOT begin with a '/'. If the file is in the root directory, pass the filename (e.g., 'compose.yaml'). If it is in a subdirectory, pass the relative path (e.g., 'sub_dir/filename.extension')."
                ),
            )

            self._ds_list_dir_tools[ds.id] = self._build_function_tool(
                async_fn=provider.list_directory,
                function_name=f"list_directory_{slug}",
                description=(
                    f"List the contents of a directory in DataSource '{ds.name}' ({ds.type}: {ds.provider}). "
                    "The path argument MUST begin with a '/' unless listing the root directory. To list the root directory, pass an empty string ''. To list a subdirectory like 'docs', pass '/docs' (NOT 'docs/' or 'docs')."
                ),
            )

            self._ds_citation_tools[ds.id] = self._build_function_tool(
                async_fn=provider.generate_citation,
                function_name=f"generate_citation_{slug}",
                description=(
                    f"Generate a formatted markdown citation link for a file in DataSource '{ds.name}' (ID: {ds.id}). "
                    "The file_path does NOT require a leading '/'. "
                    "Use this tool for every source cited in your answer."
                ),
            )

        # Step 2: Project-wide tools (search, scratchpad, plan)
        self._semantic_search_tool = self._build_function_tool(
            async_fn=self._semantic_search_wrapper,
            function_name="semantic_search",
            description=(
                "Search the project's data sources by conceptual/semantic meaning. "
                "Best for questions like 'How does X work?' or 'Where is Y implemented?'. "
                "Returns relevant file chunks with their paths and data_source_ids. "
                "You can optionally specify specific data_source_ids if you know exactly which data sources contain the information you need. "
                "Alternatively, you can provide source_type='REPOSITORY' or source_type='DOCUMENTATION' to scope the search to only code or only documentation. "
                "If both are omitted, the search will span across all available data sources."
            ),
        )

        self._grep_search_tool = self._build_function_tool(
            async_fn=self._grep_search_wrapper,
            function_name="grep_search",
            description=(
                "Find EXACT keyword or regex matches across the codebase or documentation. "
                "Accepts Postgres POSIX Regular Expressions. "
                "Use regex to catch variations: e.g. 'ingestion\\s*jobs?' matches 'ingestion job' and 'ingestion jobs'. "
                "Returns matching chunks with file paths and data_source_ids. "
                "You can optionally specify specific data_source_ids if you know exactly which data sources contain the information you need. "
                "Alternatively, you can provide source_type='REPOSITORY' or source_type='DOCUMENTATION' to scope the search to only code or only documentation. "
                "If both are omitted, the search will span across all available data sources."
            ),
        )

        self._update_research_state_tool = self._build_function_tool(
            async_fn=self._update_research_state,
            function_name="update_research_state",
            description=(
                "Record a research finding into the shared scratchpad. "
                "Call this EVERY TIME you discover relevant information. "
                "Args: finding — concise summary of what was found; "
                "source — exact file path and line range (e.g. 'src/auth/service.py:45-62'); "
                "data_source_id — UUID string of the DataSource this file belongs to."
            ),
        )

        self._write_plan_tool = self._build_function_tool(
            async_fn=self._write_plan,
            function_name="write_plan",
            description=(
                "Write or update the research plan in shared state. "
                "PlanningAgent: call this ONCE after orientating to commit the step-by-step investigation plan. "
                "ResearchAgent: call this if new discoveries require pivoting the research direction. "
                "Arg: plan — full markdown-formatted step-by-step research plan."
            ),
        )

        # Step 3: Conditional diff tool (only for scoped repositories)
        if self._scoped_repo_data_sources:
            logger.info(f"Found {len(self._scoped_repo_data_sources)} scoped repository data sources for Project={self.project_id}. Setting up internal diff_tool for Agent usage ...")
            self._setup_diff_tool()

        logger.debug(
            "Tools initialized: %d view_file, %d list_directory, %d generate_citation tools across %d DataSources, get_file_diff=%s",
            len(self._ds_view_file_tools),
            len(self._ds_list_dir_tools),
            len(self._ds_citation_tools),
            len(self.data_sources),
            "enabled" if self._get_file_diff_tool else "disabled",
        )

    def _setup_diff_tool(self):
        """
        Set up the diff tool if there are Repository DataSources configured 
        for the currrent Project with `scoped_by_issues` set to True 
        """

        # validate the DiffService is available in the case that relevant Repositories are configured 
        if not self.diff_svc:
            raise ValueError(
                "DiffService is required when scoped repository data sources exist, "
                f"but diff_svc was None. Scoped repos: {[ds.name for ds in self._scoped_repo_data_sources]}"
            )

        # Build the dynamic description enumerating valid data sources
        ds_lines = "\n".join(
            f'  - "{ds.name}" (ID: {ds.id})'
            for ds in self._scoped_repo_data_sources
        )
        self._get_file_diff_tool = self._build_function_tool(
            async_fn=self._get_file_diff_wrapper,
            function_name="get_file_diff",
            description=(
                "Retrieve the chronological list of per-pull-request diff slices for a specific file "
                "as introduced by this project.\n"
                "Each slice is one merged PR's change to the file, ordered oldest first. The latest "
                "slice is NOT the composite of all changes — reason across every slice to determine the "
                "file's net change over time.\n"
                "IMPORTANT: This tool is ONLY valid for the following data sources:\n"
                f"{ds_lines}\n"
                "Do NOT call this with any other data_source_id — it will return no results.\n"
                "Use this tool when you need to understand WHAT specifically was changed about a file "
                "in a data source due to this Project. Use view_file instead to see the file's current full state."
            ),
        )


    # ─────────────────────────────────────────────
    # Private: Tool Implementation Functions
    # ─────────────────────────────────────────────

    def _make_view_file_fn(self, ds: DataSource, provider: IngestibleDataProvider) -> Callable[[str], Any]:
        """
        Creates a custom view_file wrapper for a specific DataSource and DataProvider.
        Intercepts PDF view requests to route them through chunk retrieval, while
        standard files are routed directly to the provider.
        """

        # wrapper to route PDFs through DocStore instead of HTTP 
        async def view_file_wrapper(file_path: str) -> str:
            if file_path.lower().endswith('.pdf'):
                logger.info(f"Intercepted PDF view request for file='{file_path}' in DataSource='{ds.name}'")
                return await self.chunk_retrieval_svc.retrieve_sequential_chunks(file_path, ds.id)
            return await provider.view_file(file_path)
        
        
        return view_file_wrapper

    async def _write_plan(self, ctx: Context, plan: str) -> str:
        """
        Write or update the current research plan in shared state.
        Appends to plan_history so every revision is preserved for logging.

        Args:
            plan: Full text of the research plan (markdown step list)
        """
        async with ctx.store.edit_state() as state:
            if "plan_history" not in state:
                state["plan_history"] = []
            state["plan_history"].append(plan)
            state["plan"] = plan
        return "Research plan committed to shared state."

    async def _update_research_state(
        self, ctx: Context, finding: str, source: str, data_source_id: str
    ) -> str:
        """
        Record a research finding into the shared scratchpad.
        Call this every time relevant information is discovered.

        Args:
            finding: Concise summary of what was found
            source: Exact file path and line range (e.g. "src/auth/service.py:45-62")
            data_source_id: UUID string of the DataSource this finding belongs to
        """
        async with ctx.store.edit_state() as state:
            if "findings" not in state:
                state["findings"] = []
            state["findings"].append({
                "source": source,
                "finding": finding,
                "data_source_id": data_source_id,
            })
        return "Finding recorded in shared state."

    async def _grep_search_wrapper(
        self, key_word: str, source_type: str | None = None, data_source_ids: list[str] | None = None
    ):
        """
        Wrapper for grep/BM25 search that resolves data_source_ids from source_type
        when specific IDs are not provided, or defaults to all DataSources for the current project.

        Args:
            key_word: Keyword or POSIX regex pattern to search for
            source_type: Optional filter — 'REPOSITORY' or 'DOCUMENTATION' (ignored if data_source_ids provided)
            data_source_ids: Optional list of DataSource UUIDs to restrict search scope
        """
        resolved_ids = await self._resolve_data_source_ids(source_type, data_source_ids)

        return await self.chunk_retrieval_svc.grep_search(
            key_word,
            data_source_ids=resolved_ids,
            data_source_file_ids=self.data_source_file_ids,
            scoped_repo_data_source_ids=[str(ds.id) for ds in self._scoped_repo_data_sources]
        )

    async def _semantic_search_wrapper(
        self, query: str, source_type: str | None = None, data_source_ids: list[str] | None = None
    ):
        """
        Wrapper for semantic/vector search that resolves data_source_ids from source_type
        when specific IDs are not provided, or defaults to all DataSources for the current project.

        Args:
            query: Natural language query to search semantically
            source_type: Optional filter — 'REPOSITORY' or 'DOCUMENTATION' (ignored if data_source_ids provided)
            data_source_ids: Optional list of DataSource UUIDs to restrict search scope
        """
        resolved_ids = await self._resolve_data_source_ids(source_type, data_source_ids)

        return await self.chunk_retrieval_svc.semantic_search(
            query,
            llm=self.llm,
            data_source_ids=resolved_ids,
            data_source_file_ids=self.data_source_file_ids,
            scoped_repo_data_source_ids=[str(ds.id) for ds in self._scoped_repo_data_sources]
        )

    async def _get_file_diff_wrapper(
        self, file_path: str, data_source_id: str
    ) -> str:
        """
        Retrieve the unified diff for a specific file as introduced by this project.

        Args:
            file_path: Repo-relative path to the file (e.g. 'src/auth/service.py')
            data_source_id: UUID string of the scoped repository DataSource
        """
        # Note: This validation should have already been made above 
        if not self.diff_svc:
            raise Exception(f"DiffService not injected into Tools")

        return await self.diff_svc.get_file_diff_string(self.project_id, UUID(data_source_id), file_path)


    # ─────────────────────────────────────────────
    # Private: Utility
    # ─────────────────────────────────────────────

    async def _resolve_data_source_ids(
        self, source_type: str | None, data_source_ids: list[str] | None
    ) -> list[str]:
        """
        Resolve data source IDs for search operations.
        
        - If data_source_ids is provided, use directly (most specific — ignores source_type).
        - Else if source_type is provided, resolve via DataSourceService.
        - Else default to all project data sources that are configured as IngestibleDataProviders.
          We only extract data sources that are valid for ingestible data providers because
          these are the only ones we'll have ingested data for (for grep or semantic search).
        """
        if data_source_ids:
            return data_source_ids

        ds_type = None
        if source_type:
            try:
                ds_type = DataSourceType(source_type)
            except ValueError:
                logger.warning(f"Invalid source_type '{source_type}', falling back to all data sources")

        return await self.data_source_svc.aget_data_source_ids_by_type(self.project_id, ds_type)

    def _build_function_tool(
        self, async_fn: Callable[..., Any], function_name: str, description: str
    ) -> FunctionTool:
        """Wrap an async function as a LlamaIndex FunctionTool."""
        return FunctionTool.from_defaults(
            async_fn=async_fn,
            name=function_name,
            description=description,
        )
