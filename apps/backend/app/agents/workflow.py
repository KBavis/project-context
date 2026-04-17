from llama_index.core.agent.workflow import (AgentWorkflow, FunctionAgent, ReActAgent)
from llama_index.core.tools import FunctionTool

from llama_index.core.callbacks import CallbackManager

from app.llm import LLMBase
from typing import Any



def get_agentic_workflow(tools: list[FunctionTool], llm: LLMBase, data_sources: list[dict[str, Any]], callback_manager: CallbackManager | None = None) -> AgentWorkflow:
    """
    Retrieve the Agentic Workflow that will be leveraged based on the Tools that are available 
    based on the configured Data Source for the Project 

    TODO: Accept list of data sources as argument and pass relevant context from data sources to the agent workflow 
    """


    # TODO: Configure other agents, gathere relevant context from Data Sources being used to answer questions, 
    # use the .md files and pass relevant inputs, configure entire AgentWorkflow 

    return AgentWorkflow.from_tools_or_functions(
        tools_or_functions=tools,
        llm=llm.get_llama_idx_instance(callback_manager=callback_manager),
        system_prompt=f"""
        You are a specialized AI software engineering assistant. Your role is to help users navigate and understand their specific codebase and documentation by dynamically researching their repositories using the tools provided.

        ### DATA SOURCES (use the following to help answer users question):
        {extract_context_from_data_sources(data_sources)}

        ### OPERATIONAL GUIDELINES:

        1. **Research-First Approach (Source of Truth)**:
           - When a user asks a question, do not rely purely on your internal training data. Use your **Repository Research Tools** to find the actual code and documentation.
           - Search for keyword matches, list file structures, and read file contents to gather evidence.
           - Prioritize information found in the actual repositories over general assumptions.

        2. **Iterative Discovery ("Jumping Around")**:
           - Start with a broad search to find relevant entry points (e.g., READMEs, service files, API routes).
           - Once a relevant component is found, follow its dependencies. If `Class A` uses `Service B`, search for `Service B` to understand the full context.
           - Continue researching until you have enough information to answer the user's question completely.

        3. **Tone & Format**:
           - Professional, technically accurate, and concise.
           - Use triple backticks with language identifiers (e.g., ```python) for code snippets.
           - Use **bold** for file paths and key technical terms.
           - Always cite the file path when providing snippets or explaining logic.
        """,
    )
   


def extract_context_from_data_sources(data_sources: list[dict[str, Any]]) -> str:
    """
    Extract relevant context from data sources to be passed to the agent workflow

                    "provider": data_source.provider,
                "name": data_source.name,
                "branch": data_source.branch,
                "config": {"url": data_source.url},
    """
    
    context_list = []
    for ds in data_sources:
        context_list.append(f"""
            Provider: {ds['provider']}
            Name: {ds['name']}
            Branch: {ds['branch']}
            URL: {ds['config']['url']}
        """)
    
    return "\n".join(context_list)
        
    










    