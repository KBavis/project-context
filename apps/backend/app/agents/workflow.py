from collections import defaultdict
from enum import Enum
from llama_index.core.agent.workflow import (AgentWorkflow, FunctionAgent, ReActAgent)
from llama_index.core.tools import FunctionTool

from llama_index.core.callbacks import CallbackManager
from workflows import context

from app.llm import LLMBase
from typing import Any

from app.models.data_source import DataSourceType

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
    """
    Extract relevant context from data sources to be passed to the agent workflow
    """
    if not data_sources:
        logger.warning(f"No data sources configured for this project")
        return "No data sources configured for this project"
    

    lines: list[str] = []
    for ds in data_sources:
        lines.append(
            f"- [{ds.get('type', 'unknown')}: {ds.get('provider', 'unknown')}] {ds.get('name', 'unnamed')} "
            f"(branch: {ds.get('branch', 'n/a')}, url: {ds.get('config', {}).get('url', 'n/a')})"
        )
    return "\n".join(lines)


def _load_prompt(agent_type: str, context: dict[str, Any] = {}) -> str:
    """
    Load System Prompt for a given Agent Type 

    Args:
        agent_type (AgentType): Type of Agent to load prompt for
        context (str): Context to be included in the system prompt
    """

    return ""
    

def _summarize_available_tools(tools: list[FunctionTool]) -> str:
    """
    Summarize the available tools based on the configured data sources
    """

    return ""
    


##################################
# Agent Factory Functions
##################################

def _build_orchestrator_agent(
    llm: LLMBase,
    all_tools: list[FunctionTool],
    callback_manager: CallbackManager | None,
    data_sources: list[dict[str, Any]]
) -> FunctionAgent:
    """ Build Orchestrator Agent """

    system_prompt: str = _load_prompt(
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
            "Parses the users question and determines which data sources " +
            "are relevant to answer the question (REPOSITORY, DOCUMENTATION, etc). " +
            "Always run first."
        ),
        system_prompt=system_prompt,
        tools=[],# Orchestrator shouldn't leverage tool, just orchestrate the workflow 
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=["CodeAgent", "DocsAgent", "SynthAgent"]
    )


def _build_code_agent(
    llm: LLMBase,
    code_tools: list[FunctionTool],
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    """Build the CodeAgent with only code-scoped tools."""
    system_prompt = _load_prompt(AgentType.CODE)
    return FunctionAgent(
        name="CodeAgent",
        description=(
            "Searches and reads source code files to find implementation details, "
            "edge case handling, and concrete behaviour. Receives only code repository "
            "tools."
        ),
        system_prompt=system_prompt,
        tools=code_tools,
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=["SynthAgent"],
    )
 
 
def _build_docs_agent(
    llm: LLMBase,
    docs_tools: list[FunctionTool],
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    """Build the DocsAgent with only documentation-scoped tools."""
    system_prompt = _load_prompt(AgentType.DOCS)
    return FunctionAgent(
        name="DocsAgent",
        description=(
            "Searches and reads documentation sources (wikis, READMEs, ADRs, API "
            "references) to find design intent, architecture decisions, and guides. "
            "Receives only documentation tools."
        ),
        system_prompt=system_prompt,
        tools=docs_tools,
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=["SynthAgent"],
    )
 
 
def _build_synth_agent(
    llm: LLMBase,
    callback_manager: CallbackManager | None,
) -> FunctionAgent:
    """Build the SynthAgent that collates findings into a user-facing answer."""
    system_prompt = _load_prompt(AgentType.SYNTH)
    return FunctionAgent(
        name="SynthAgent",
        description=(
            "Receives structured findings from CodeAgent and/or DocsAgent and writes "
            "a single, well-cited answer for the user. Always runs last."
        ),
        system_prompt=system_prompt,
        # SynthAgent never calls external tools — it only synthesises.
        tools=[],
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        can_handoff_to=[],
    )


#########################
# Public Facing Functions
#########################

def get_agentic_workflow(tools: defaultdict[DataSourceType, list[FunctionTool]], llm: LLMBase, data_sources: list[dict[str, Any]], callback_manager: CallbackManager | None = None) -> AgentWorkflow:
    """Build and return the full multi-agent Project Helper workflow.
 
    The workflow is assembled dynamically based on which tool types are present
    in `tools`. If a research plan later requires a tool type that isn't present,
    a MissingMCPError is raised before any specialist agent is invoked.
 
    tools:
        - all FunctionTools made available by the user's MCP configuration.
    llm:
        - LLM wrapper (must implement get_llama_idx_instance).
    data_sources:
        - List of data source metadata dicts from the project configuration.
    callback_manager:
        - Optional LlamaIndex CallbackManager for tracing / logging.
    """

    all_tools = [tool for tool_list in tools.values() for tool in tool_list] # extract all potential available tools based on configured dat asources 
    orchestrator = _build_orchestrator_agent(
        llm=llm,
        all_tools=all_tools,
        callback_manager=callback_manager,
        data_sources=data_sources
    )
   

        
    










    