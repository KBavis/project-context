from llama_index.core.agent.workflow import AgentWorkflow, FunctionAgent
from llama_index.core.tools import FunctionTool
from llama_index.core.callbacks import CallbackManager

from app.agents.tools import Tools
from app.llm import LLMBase
from app.models.data_source import DataSource, DataSourceType
from app.pydantic.agent import AgentType, AgentName
from typing import Any
from pathlib import Path
import re

import logging
logger = logging.getLogger(__name__)


###########################
# Helper Functions
###########################

def _load_prompt(agent_type: AgentType, context: dict[str, Any] = {}) -> str:
    """
    Load system prompt from the corresponding .md file and interpolate context values.
    Looks for prompts/{agent_type.value}.md relative to this file.
    """
    prompts_dir = Path(__file__).parent / "prompts"
    prompt_path = prompts_dir / f"{agent_type.value}.md"
    logger.debug("Loading prompt for %s from %s", agent_type.value, prompt_path)

    if not prompt_path.exists():
        available = [p.stem for p in prompts_dir.glob("*.md")]
        raise FileNotFoundError(
            f"Prompt file not found: {prompt_path}. Available prompts: {available}"
        )

    text = prompt_path.read_text(encoding="utf-8")
    for key, value in context.items():
        text = text.replace(f"{{{key}}}", str(value))
    return text


def _build_data_source_context(data_sources: list[DataSource]) -> str:
    """
    Build a human-readable mapping of DataSources to their concrete tool names.
    Injected into each agent's system prompt so the agent can directly select
    the right tool for the right DataSource without any intermediate lookup.
    """
    if not data_sources:
        return "No data sources configured for this project."

    lines: list[str] = []
    for ds in data_sources:
        slug = re.sub(r"[^a-z0-9]+", "_", ds.name.lower()).strip("_")[:30]
        lines.append(
            f"- [{ds.type}: {ds.provider}] **{ds.name}** (ID: {ds.id}, URL: {ds.url})\n"
            f"  Tools: `view_file_{slug}`, `list_directory_{slug}`, `generate_citation_{slug}`"
        )
    return "\n".join(lines)



def _build_mcp_context(
    data_sources: list[DataSource],
    mcp_tools: dict[str, list[FunctionTool]],
) -> str:
    """
    Build a human-readable mapping of DataSource → available MCP tools.
    Injected into the ResearchAgent's prompt so it knows which action-oriented
    MCP tools are available for each DataSource.
    """
    if not data_sources:
        return "No data sources configured."

    lines: list[str] = []
    for ds in data_sources:
        ds_mcp = mcp_tools.get(str(ds.id), [])
        if ds_mcp:
            tool_names = ", ".join(t.metadata.name or "unnamed" for t in ds_mcp)
        else:
            tool_names = "(none configured)"
        lines.append(f"- {ds.name} (ID: {ds.id}): {tool_names}")

    return "\n".join(lines) if lines else "No MCP tools configured."


##################################
# Agent Factory Functions
##################################

def _build_research_agent(
    llm: LLMBase,
    research_tools: list[FunctionTool],
    data_sources: list[DataSource],
    mcp_tools: dict[str, list[FunctionTool]],
    refined_question: str,
    scope_summary: str,
    callback_manager: CallbackManager | None,
    diff_tool_registered: bool = False,
    project_context: str = "",
    research_depth_directive: str = "",
) -> FunctionAgent:
    """
    ResearchAgent — the single agent in the workflow. Self-plans, then executes by
    reading files, navigating directories, and running searches, logging every finding
    via update_research_state. Does NOT write the final answer (a separate streaming
    answer step turns findings into the user-facing response).
    """
    diff_tool_context = ""
    if diff_tool_registered:
        diff_tool_context = (
            "**Diff Tool**\n"
            "- **`get_file_diff(file_path, data_source_id)`** — Retrieve the unified diff for a specific file. "
            "ONLY call this tool for the valid list of data sources explicitly provided in the tool description. "
            "Use this tool whenever the user asks about what was modified, added, or changed by this project. "
            "This tool is the ultimate source of truth for grounding your understanding in the ACTUAL changes introduced by the Project to a data source. "
            "Always use this to see exactly what lines of code were touched. "
            "Use `view_file_<slug>` instead ONLY when you need to see the file's current full state and surrounding context."
        )

    system_prompt = _load_prompt(
        AgentType.RESEARCH,
        context={
            "refined_question": refined_question,
            "project_context": project_context,
            "data_sources_context": _build_data_source_context(data_sources),
            "mcp_context": _build_mcp_context(data_sources, mcp_tools),
            "diff_tool_context": diff_tool_context,
            "scope_summary": scope_summary,
            "research_depth_directive": research_depth_directive,
        },
    )
    return FunctionAgent(
        name=AgentName.RESEARCH,
        description=(
            "Self-plans and investigates the project's data sources: reads files, navigates "
            "directories, searches, and logs every finding to the shared scratchpad."
        ),
        system_prompt=system_prompt,
        tools=research_tools,
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=[],
        allow_parallel_tool_calls=True,
    )


#########################
# Public Facing Functions
#########################

def get_agentic_workflow(
    mcp_tools: dict[str, list[FunctionTool]],
    llm: LLMBase,
    data_sources: list[DataSource],
    tool_manager: Tools,
    refined_question: str,
    question_type: str,
    research_depth: str = "standard",
    scope_summary: str = "",
    project_context: str = "",
    callback_manager: CallbackManager | None = None,
) -> AgentWorkflow:
    """
    Build and return the single-agent research workflow.

    The workflow contains one self-planning ResearchAgent that gathers and logs findings.
    The final user-facing answer is produced separately by a streaming completion (see
    build_answer_prompt) so it can be streamed cleanly and cited deterministically.

    Args:
        mcp_tools: MCP tools keyed by data_source_id (UUID string).
        llm: LLM wrapper (must implement get_llama_idx_instance).
        data_sources: Filtered list of relevant DataSources from Diagnosis.
        tool_manager: Initialized Tools instance for this workflow run.
        refined_question: Clarified user question from Diagnosis.
        question_type: Question classification from Diagnosis.
        scope_summary: Summary of project-scoped diffs to inject into prompts.
        project_context: Human-readable summary of the project being assisted.
        callback_manager: Optional LlamaIndex CallbackManager for tracing / token counting.
    """
    research_tools = tool_manager.get_research_tools(mcp_tools)

    total_mcp = sum(len(t) for t in mcp_tools.values())
    logger.info(
        "Building single-agent workflow — research_tools=%d (incl. %d MCP)",
        len(research_tools),
        total_mcp,
    )

    research_agent = _build_research_agent(
        llm=llm,
        research_tools=research_tools,
        data_sources=data_sources,
        mcp_tools=mcp_tools,
        refined_question=refined_question,
        scope_summary=scope_summary,
        project_context=project_context,
        callback_manager=callback_manager,
        diff_tool_registered=tool_manager._get_file_diff_tool is not None,
        research_depth_directive=_research_depth_directive(research_depth),
    )

    return AgentWorkflow(
        agents=[research_agent],
        root_agent=AgentName.RESEARCH,
    )


def build_answer_prompt(
    refined_question: str,
    project_context: str,
    scope_summary: str,
    findings: list[dict],
) -> str:
    """
    Build the prompt for the final streaming answer completion. Injects the shared
    Answer Constitution and the numbered research findings. The 1-based finding index
    aligns with Tools.build_citation_map so the answer's `cite:<id>` markers resolve.
    """
    return _load_prompt(
        AgentType.ANSWER,
        context={
            "constitution": _load_constitution(),
            "project_context": project_context,
            "refined_question": refined_question,
            "scope_summary": scope_summary,
            "findings": _format_findings(findings),
        },
    )


def _load_constitution() -> str:
    """Load the shared Answer Constitution prompt fragment."""
    path = Path(__file__).parent / "prompts" / "_constitution.md"
    return path.read_text(encoding="utf-8")


def _research_depth_directive(research_depth: str) -> str:
    """
    Turn the diagnosis research_depth into an explicit pacing directive for the research
    agent. The budget (max_iterations) is a hard ceiling; this steers how aggressively the
    agent investigates within it.
    """
    depth = (research_depth or "standard").lower()
    if depth == "shallow":
        return (
            "**Research depth: SHALLOW.** This is a straightforward question. Use at most 2–3 "
            "targeted lookups. If you need broad context first, a single `semantic_search` across "
            "docs and code is a good start — otherwise go straight to the specific file(s) you need. "
            "Stop and finish as soon as you can answer; do not keep exploring."
        )
    if depth == "deep":
        return (
            "**Research depth: DEEP.** This warrants thorough investigation across multiple files "
            "and components. Trace the relevant behavior fully, but still stop once new searches "
            "stop surfacing new information."
        )
    return (
        "**Research depth: STANDARD.** Investigate the relevant areas enough to answer accurately, "
        "then stop. Do not exhaustively trace every reference or read files that won't change the answer."
    )


def _format_findings(findings: list[dict]) -> str:
    """
    Render findings as a numbered list for the answer prompt. The 1-based index is the
    citation id the answer references via `cite:<id>` and must match build_citation_map.
    """
    if not findings:
        return "No findings were gathered during research."
    lines: list[str] = []
    for idx, f in enumerate(findings, start=1):
        source = f.get("source", "(unknown source)")
        ds_id = f.get("data_source_id", "")
        text = f.get("finding", "")
        lines.append(f"[{idx}] source: {source} (data_source_id: {ds_id})\n    {text}")
    return "\n".join(lines)