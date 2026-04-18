from collections import defaultdict
from enum import Enum
from llama_index.core.agent.workflow import AgentWorkflow, FunctionAgent
from llama_index.core.tools import FunctionTool
from llama_index.core.callbacks import CallbackManager

from app.llm import LLMBase
from app.models.data_source import DataSourceType
from typing import Any

import logging
logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    CODE = "code"
    DOCS = "docs"
    SYNTH = "synth"


###########################
# Helper Workflow Functions
###########################

def _extract_context_from_data_sources(data_sources: list[dict[str, Any]]) -> str:
    if not data_sources:
        logger.warning("No data sources configured for this project")
        return "No data sources configured for this project"

    lines: list[str] = []
    for ds in data_sources:
        lines.append(
            f"- [{ds.get('type', 'unknown')}: {ds.get('provider', 'unknown')}] "
            f"{ds.get('name', 'unnamed')} "
            f"(branch: {ds.get('branch', 'n/a')}, url: {ds.get('config', {}).get('url', 'n/a')})"
        )
    return "\n".join(lines)


def _load_prompt(agent_type: AgentType, context: dict[str, Any] = {}) -> str:
    # TODO: load from .md files
    return ""


def _summarize_available_tools(tools: list[FunctionTool]) -> str:
    # TODO: build human-readable tool summary for orchestrator context
    return ""


##################################
# Agent Factory Functions
##################################

def _build_orchestrator_agent(
    llm: LLMBase,
    all_tools: list[FunctionTool],
    data_sources: list[dict[str, Any]],
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
        name="OrchestratorAgent",
        description=(
            "Parses the user's question and determines which data sources "
            "are relevant (REPOSITORY, DOCUMENTATION, etc). Always runs first."
        ),
        system_prompt=system_prompt,
        tools=[],
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        # Only hand off to agents that were actually built
        can_handoff_to=available_agents,
    )


def _build_code_agent(
    llm: LLMBase,
    repo_tools: list[FunctionTool],
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    """
    CodeAgent receives only REPOSITORY tools.
    Prompted to look at source files (.py, .ts, etc) — not markdown.
    """
    system_prompt = _load_prompt(AgentType.CODE)
    return FunctionAgent(
        name="CodeAgent",
        description=(
            "Searches and reads source code files to find implementation details, "
            "edge case handling, and concrete behaviour. "
            "Uses REPOSITORY tools only — focuses on source files, not markdown."
        ),
        system_prompt=system_prompt,
        tools=repo_tools,
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=["SynthAgent"],
    )


def _build_docs_agent(
    llm: LLMBase,
    repo_tools: list[FunctionTool],
    documentation_tools: list[FunctionTool],
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    """
    DocsAgent receives BOTH REPOSITORY tools (for README/docs folders) and
    DOCUMENTATION tools (Confluence, Notion, etc).
    Prompted to focus on markdown files, /docs paths, and dedicated doc platforms.
    """
    system_prompt = _load_prompt(AgentType.DOCS)
    return FunctionAgent(
        name="DocsAgent",
        description=(
            "Searches and reads documentation — READMEs, /docs folders, ADRs from "
            "repositories, plus dedicated documentation platforms (Confluence, Notion). "
            "Uses both REPOSITORY and DOCUMENTATION tools."
        ),
        system_prompt=system_prompt,
        tools=[*repo_tools, *documentation_tools],
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=["SynthAgent"],
    )


def _build_synth_agent(
    llm: LLMBase,
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    system_prompt = _load_prompt(AgentType.SYNTH)
    return FunctionAgent(
        name="SynthAgent",
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
    tools: defaultdict[DataSourceType, list[FunctionTool]],
    llm: LLMBase,
    data_sources: list[dict[str, Any]],
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
    repo_tools: list[FunctionTool] = tools.get(DataSourceType.REPOSITORY, [])
    documentation_tools: list[FunctionTool] = tools.get(DataSourceType.DOCUMENTATION, [])
    all_tools: list[FunctionTool] = [*repo_tools, *documentation_tools]

    logger.info(
        "Building ProjectHelper workflow — repo_tools=%d, documentation_tools=%d",
        len(repo_tools),
        len(documentation_tools),
    )

    agents: list[FunctionAgent] = []
    # Track which specialist agents exist so the orchestrator's
    # can_handoff_to list only references agents that were actually built.
    available_specialist_agents: list[str] = ["SynthAgent"]

    if repo_tools:
        agents.append(_build_code_agent(llm, repo_tools, callback_manager))
        available_specialist_agents.append("CodeAgent")

    # DocsAgent is useful if we have EITHER repo tools (for markdown/docs folders)
    # OR dedicated documentation platform tools — or both.
    if repo_tools or documentation_tools:
        agents.append(_build_docs_agent(llm, repo_tools, documentation_tools, callback_manager))
        available_specialist_agents.append("DocsAgent")

    orchestrator = _build_orchestrator_agent(
        llm=llm,
        all_tools=all_tools,
        data_sources=data_sources,
        available_agents=available_specialist_agents,
        callback_manager=callback_manager,
    )

    agents.append(_build_synth_agent(llm, callback_manager))

    return AgentWorkflow(
        agents=[orchestrator, *agents],
        root_agent="OrchestratorAgent",
    )










    