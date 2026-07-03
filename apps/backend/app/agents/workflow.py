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

def _build_planning_agent(
    llm: LLMBase,
    planning_tools: list[FunctionTool],
    data_sources: list[DataSource],
    refined_question: str,
    question_type: str,
    scope_summary: str,
    callback_manager: CallbackManager | None,
    diff_tool_registered: bool = False,
) -> FunctionAgent:
    """
    PlanningAgent — root agent. Orients via semantic search and directory exploration,
    writes a structured research plan, then hands off to ResearchAgent.
    """
    diff_tool_context = ""
    if diff_tool_registered:
        diff_tool_context = (
            "**Diff Tool (Available to ResearchAgent)**\n"
            "- **`get_file_diff(file_path, data_source_id)`** — Retrieve the unified diff for a specific file. "
            "Instruct the ResearchAgent to use this tool whenever the user asks about what was modified, added, or changed by this project. "
            "This tool is the ultimate source of truth for grounding answers in the ACTUAL changes introduced by the project to a data source. "
            "Instruct the ResearchAgent to use `view_file_<slug>` only when it needs to see the surrounding context of those changes."
        )

    system_prompt = _load_prompt(
        AgentType.PLANNING,
        context={
            "refined_question": refined_question,
            "question_type": question_type,
            "data_sources_context": _build_data_source_context(data_sources),
            "diff_tool_context": diff_tool_context,
            "scope_summary": scope_summary,
        },
    )
    return FunctionAgent(
        name=AgentName.PLANNING,
        description=(
            "Orients by semantically searching for starting-point files and exploring directory structure. "
            "Writes a step-by-step research plan. Always runs first."
        ),
        system_prompt=system_prompt,
        tools=planning_tools,
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=[AgentName.RESEARCH],
    )


def _build_research_agent(
    llm: LLMBase,
    research_tools: list[FunctionTool],
    data_sources: list[DataSource],
    mcp_tools: dict[str, list[FunctionTool]],
    refined_question: str,
    scope_summary: str,
    callback_manager: CallbackManager | None,
    diff_tool_registered: bool = False,
) -> FunctionAgent:
    """
    ResearchAgent — executes the plan by reading files, navigating directories,
    and running searches. Logs all findings via update_research_state.
    May revise the plan if new discoveries change direction.
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
            "data_sources_context": _build_data_source_context(data_sources),
            "mcp_context": _build_mcp_context(data_sources, mcp_tools),
            "diff_tool_context": diff_tool_context,
            "scope_summary": scope_summary,
        },
    )
    return FunctionAgent(
        name=AgentName.RESEARCH,
        description=(
            "Executes the research plan: reads files, navigates directories, searches for keywords. "
            "Logs every finding to the shared scratchpad. Hands off to SynthAgent when done."
        ),
        system_prompt=system_prompt,
        tools=research_tools,
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=[AgentName.SYNTH],
    )


def _build_synth_agent(
    llm: LLMBase,
    synthesis_tools: list[FunctionTool],
    data_sources: list[DataSource],
    refined_question: str,
    scope_summary: str,
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    """
    SynthesisAgent — reads accumulated findings from the handoff message,
    generates citations via per-DataSource generate_citation tools,
    and writes the final user-facing answer. Always runs last.
    """
    system_prompt = _load_prompt(
        AgentType.SYNTH,
        context={
            "refined_question": refined_question,
            "data_sources_context": _build_data_source_context(data_sources),
            "scope_summary": scope_summary,
        },
    )
    return FunctionAgent(
        name=AgentName.SYNTH,
        description=(
            "Synthesizes accumulated research findings into a comprehensive, well-cited answer. "
            "Always runs last."
        ),
        system_prompt=system_prompt,
        tools=synthesis_tools,
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=[],
    )


#########################
# Public Facing Function
#########################

def get_agentic_workflow(
    mcp_tools: dict[str, list[FunctionTool]],
    llm: LLMBase,
    data_sources: list[DataSource],
    tool_manager: Tools,
    refined_question: str,
    question_type: str,
    scope_summary: str = "",
    callback_manager: CallbackManager | None = None,
) -> AgentWorkflow:
    """
    Build and return the three-agent state machine workflow:
      PlanningAgent → ResearchAgent → SynthesisAgent

    Args:
        mcp_tools: MCP tools keyed by data_source_id (UUID string).
        llm: LLM wrapper (must implement get_llama_idx_instance).
        data_sources: Filtered list of relevant DataSources from Diagnosis.
        tool_manager: Initialized Tools instance for this workflow run.
        refined_question: Clarified user question from Diagnosis.
        question_type: Question classification from Diagnosis.
        scope_summary: Summary of project-scoped diffs to inject into prompts.
        callback_manager: Optional LlamaIndex CallbackManager for tracing.
    """
    planning_tools  = tool_manager.get_planning_tools()
    research_tools  = tool_manager.get_research_tools(mcp_tools)
    synthesis_tools = tool_manager.get_synthesis_tools()

    total_mcp = sum(len(t) for t in mcp_tools.values())
    logger.info(
        "Building workflow — planning_tools=%d, research_tools=%d (incl. %d MCP), synthesis_tools=%d",
        len(planning_tools),
        len(research_tools),
        total_mcp,
        len(synthesis_tools),
    )

    planning_agent = _build_planning_agent(
        llm=llm,
        planning_tools=planning_tools,
        data_sources=data_sources,
        refined_question=refined_question,
        question_type=question_type,
        scope_summary=scope_summary,
        callback_manager=callback_manager,
        diff_tool_registered=tool_manager._get_file_diff_tool is not None,
    )

    research_agent = _build_research_agent(
        llm=llm,
        research_tools=research_tools,
        data_sources=data_sources,
        mcp_tools=mcp_tools,
        refined_question=refined_question,
        scope_summary=scope_summary,
        callback_manager=callback_manager,
        diff_tool_registered=tool_manager._get_file_diff_tool is not None,
    )

    synth_agent = _build_synth_agent(
        llm=llm,
        synthesis_tools=synthesis_tools,
        data_sources=data_sources,
        refined_question=refined_question,
        scope_summary=scope_summary,
        callback_manager=callback_manager,
    )

    return AgentWorkflow(
        agents=[planning_agent, research_agent, synth_agent],
        root_agent=AgentName.PLANNING,
    )