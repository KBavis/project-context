from collections import defaultdict
from llama_index.core.agent.workflow import AgentWorkflow, FunctionAgent
from llama_index.core.tools import FunctionTool
from llama_index.core.callbacks import CallbackManager

from app.llm import LLMBase
from app.models.data_source import DataSource, DataSourceType
from app.pydantic.agent import AgentType, AgentName
from typing import Any
from pathlib import Path

import logging
logger = logging.getLogger(__name__)


###########################
# Helper Workflow Functions
###########################

def _extract_context_from_data_sources(data_sources: list[DataSource], type_filter: str | None = None) -> str:
    """
    Build a human-readable list of data sources for agent system prompts.
    Pass `type_filter` (e.g. DataSourceType.REPOSITORY) to restrict to one type.
    """
    filtered = [
        ds for ds in data_sources
        if type_filter is None or ds.type == type_filter
    ]
    if not filtered:
        return f"No {type_filter or ''} data sources configured for this project.".strip()

    lines: list[str] = []
    for ds in filtered:
        lines.append(
            f"- [{ds.type}: {ds.provider}] "
            f"{ds.name} "
            f"(branch: {ds.branch}, url: {ds.url})"
        )
    return "\n".join(lines)


def _load_prompt(agent_type: AgentType, context: dict[str, Any] = {}) -> str:
    """
    Load system prompt from the corresponding .md file and interpolate context values.
    Looks for prompts/{agent_type.value}.md relative to this file.
    """

    prompts_dir = Path(__file__).parent / "prompts"
    prompt_path = prompts_dir / f"{agent_type.value}.md"
    logger.debug(f"Loading prompt for {agent_type.value} from {prompt_path}")

    if not prompt_path.exists():
        available = [p.stem for p in prompts_dir.glob("*.md")]
        raise FileNotFoundError(
            f"Prompt file not found: {prompt_path}. Available prompts: {available}"
        )

    text = prompt_path.read_text(encoding="utf-8")

    for key, value in context.items():
        text = text.replace(f"{{{key}}}", str(value))

    return text


def _summarize_available_tools(tools: list[FunctionTool]) -> str:
    """
    Build a human-readable summary of available tools for the orchestrator's
    system prompt, so it knows what it can and cannot ask downstream agents to do.
    """
    if not tools:
        return "No tools are currently available."

    lines: list[str] = ["Available tools:"]
    for tool in tools:
        name = tool.metadata.name or "unnamed"
        description = (tool.metadata.description or "no description").strip().splitlines()[0]
        lines.append(f"  - {name}: {description}")

    return "\n".join(lines)


##################################
# Shared Internal Tools

# TODO: SHIFT THIS LOGIC OVER TO agent/tools.py
##################################



##################################
# Agent Factory Functions
##################################

def _build_orchestrator_agent(
    llm: LLMBase,
    all_tools: list[FunctionTool],
    internal_tools: list[FunctionTool],
    data_sources: list[DataSource],
    available_agents: list[str],
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    system_prompt = _load_prompt(
        AgentType.ORCHESTRATOR,
        context={
            "data_sources_context": (
                _extract_context_from_data_sources(data_sources)
                + "\n\n"
                + _summarize_available_tools(all_tools)
            ),
        },
    )
    return FunctionAgent(
        name=AgentName.ORCHESTRATOR,
        description=(
            "Parses the user's question and determines which data sources "
            "are relevant (REPOSITORY, DOCUMENTATION, etc). Always runs first."
        ),
        system_prompt=system_prompt,
        tools=[*internal_tools],
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        # Only hand off to agents that were actually built
        can_handoff_to=available_agents,
    )


def _build_code_agent(
    llm: LLMBase,
    repo_tools: list[FunctionTool],
    internal_tools: list[FunctionTool],
    data_sources: list[DataSource],
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    """
    CodeAgent receives only REPOSITORY tools.
    Prompted to look at source files (.py, .ts, etc) — not markdown.
    """
    system_prompt = _load_prompt(
        AgentType.CODE,
        context={
            "data_sources_context": _extract_context_from_data_sources(
                data_sources, type_filter=DataSourceType.REPOSITORY
            )
        },
    )
    return FunctionAgent(
        name=AgentName.CODE,
        description=(
            "Searches and reads source code files to find implementation details, "
            "edge case handling, and concrete behaviour. "
            "Uses REPOSITORY tools only — focuses on source files, not markdown."
        ),
        system_prompt=system_prompt,
        tools=[*repo_tools, *internal_tools],
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=["OrchestratorAgent"],
    )

def _build_docs_agent(
    llm: LLMBase,
    repo_tools: list[FunctionTool],
    documentation_tools: list[FunctionTool],
    internal_tools: list[FunctionTool],
    data_sources: list[DataSource],
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    """
    DocsAgent receives BOTH REPOSITORY tools (for README/docs folders) and
    DOCUMENTATION tools (Confluence, Notion, etc).
    Prompted to focus on markdown files, /docs paths, and dedicated doc platforms.
    """
    # Show both REPOSITORY sources (for in-repo docs) and DOCUMENTATION platform sources
    repo_context = _extract_context_from_data_sources(data_sources, type_filter=DataSourceType.REPOSITORY)
    docs_context = _extract_context_from_data_sources(data_sources, type_filter=DataSourceType.DOCUMENTATION)
    combined_context = (
        f"Repository sources (README/docs folders):\n{repo_context}"
        f"\n\nDocumentation platform sources:\n{docs_context}"
    )
    system_prompt = _load_prompt(
        AgentType.DOCS,
        context={"data_sources_context": combined_context},
    )
    return FunctionAgent(
        name=AgentName.DOCS,
        description=(
            "Searches and reads documentation — READMEs, /docs folders, ADRs from "
            "repositories, plus dedicated documentation platforms (Confluence, Notion). "
            "Uses both REPOSITORY and DOCUMENTATION tools."
        ),
        system_prompt=system_prompt,
        tools=[*repo_tools, *documentation_tools, *internal_tools],
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=["OrchestratorAgent"],
    )

def _build_synth_agent(
    llm: LLMBase,
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    system_prompt = _load_prompt(AgentType.SYNTH)
    return FunctionAgent(
        name=AgentName.SYNTH,
        description=(
            "Receives structured findings from CodeAgent and/or DocsAgent and writes "
            "a single, well-cited answer for the user. Always runs last."
        ),
        system_prompt=system_prompt,
        tools=[],
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=[],
    )


#########################
# Public Facing Functions
#########################

def get_agentic_workflow(
    mcp_tools: defaultdict[DataSourceType, list[FunctionTool]],
    llm: LLMBase,
    data_sources: list[DataSource],
    internal_tools: list[FunctionTool],
    callback_manager: CallbackManager | None = None,
) -> AgentWorkflow:
    """Build and return the full multi-agent Project Helper workflow.

    tools:
        Mapping of DataSourceType → list of FunctionTools for that source type.
        Expected keys: DataSourceType.REPOSITORY, DataSourceType.DOCUMENTATION
    llm:
        LLM wrapper (must implement get_llama_idx_instance).
    data_sources:
        List of data source metadata dicts from the project configuration.
    callback_manager:
        Optional LlamaIndex CallbackManager for tracing / logging.
    """
    repo_tools: list[FunctionTool] = mcp_tools.get(DataSourceType.REPOSITORY, [])
    documentation_tools: list[FunctionTool] = mcp_tools.get(DataSourceType.DOCUMENTATION, [])
    all_tools: list[FunctionTool] = [*repo_tools, *documentation_tools, *internal_tools]

    logger.info(
        "Building ProjectHelper workflow — repo_tools=%d, documentation_tools=%d, internal_tools=%d",
        len(repo_tools),
        len(documentation_tools),
        len(internal_tools)
    )

    agents: list[FunctionAgent] = []
    # Track which specialist agents exist so the orchestrator's
    # can_handoff_to list only references agents that were actually built.
    available_specialist_agents: list[str] = ["SynthAgent"]

    if repo_tools:
        agents.append(_build_code_agent(llm, repo_tools, internal_tools, data_sources, callback_manager))
        available_specialist_agents.append("CodeAgent")

    # DocsAgent is useful if we have EITHER repo tools (for markdown/docs folders)
    # OR dedicated documentation platform tools — or both.
    if repo_tools or documentation_tools:
        agents.append(_build_docs_agent(llm, repo_tools, documentation_tools, internal_tools, data_sources, callback_manager))
        available_specialist_agents.append("DocsAgent")

    orchestrator = _build_orchestrator_agent(
        llm=llm,
        all_tools=all_tools,
        internal_tools=internal_tools,
        data_sources=data_sources,
        available_agents=available_specialist_agents,
        callback_manager=callback_manager,
    )

    agents.append(_build_synth_agent(llm, callback_manager))

    return AgentWorkflow(
        agents=[orchestrator, *agents],
        root_agent="OrchestratorAgent",
    )










    