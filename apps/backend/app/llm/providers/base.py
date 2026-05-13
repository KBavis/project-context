from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable
import json

from llama_index.core.llms.function_calling import FunctionCallingLLM
from llama_index.core.callbacks import CallbackManager


class LLMBase(ABC):

    ###############
    # Generic functionality that can be used by all LLM providers
    ###############

    async def send_message(self, prompt: str):
        """
        Send a message to the LLM and return the response

        Args:
            prompt (str): The prompt to send to the LLM
        """

        valid = await self.validate_context_length(prompt)

        # validate context length 
        if not valid:
            raise ValueError("Prompt exceeds maximum context length")

        
        llm_instance = self.get_llama_idx_instance()
        return await llm_instance.acomplete(prompt)


    
    async def validate_context_length(self, prompt: str, current_token_count: int = 0) -> bool:
        """
        Validate that the current token count does not exceed the maximum context length.

        Returns:
            bool: A boolean indicating if the prompt is valid.

        Args:
            prompt (str): The prompt to validate.
            current_token_count (int): The current token count (i.e if conversation history maintained)
        """
        # get max context length of model
        max_tokens = await self.get_max_context_length() #TODO: This accounts for strictly user input tokens, but should account for both

        total_input_tokens = await self.tokenize(prompt)
        
        return len(total_input_tokens) + current_token_count <= max_tokens

    async def diagnose_question(
        self, 
        prompt: str, 
        data_sources_info: str, 
        internal_tools_info: str, 
        mcp_tools_info: str
    ) -> dict:
        """
        Phase 1: Diagnosis. Analyze the user's question against available data sources and tools to determine the 
        optimal research trajectory and filter out unnecessary context.
        """
        diagnosis_prompt = f"""
        TASK: You are the Diagnosis Agent for a coding assistant workflow. 
        Your job is to analyze the USER_QUESTION and determine exactly which Data Sources and MCP Tools are necessary to answer it.

        AVAILABLE DATA SOURCES:
        {data_sources_info}

        AVAILABLE INTERNAL TOOLS (Always active, do not select these, they are provided for context so you know what base capabilities exist):
        {internal_tools_info}

        AVAILABLE MCP TOOLS (External connections):
        {mcp_tools_info}

        CRITICAL RULES:
        1. "required_data_sources" should be a list of Data Source IDs that are relevant. If the question requires general knowledge or all sources, include all relevant IDs.
        2. "required_mcp_tools" should be a list of MCP Tool Names. ONLY include an MCP tool if the Internal Tools cannot accomplish the task. MCP tools are typically for external integrations (e.g. GitHub API, Jira API). If the user just wants to know about the codebase, rely on internal tools and leave this list empty.
        3. Your ONLY output MUST be a valid JSON object. Do NOT wrap it in markdown block quotes.

        OUTPUT_FORMAT:
        {{
            "question_type": "Brief classification of the question (e.g. 'Deep Research', 'General Inquiry', 'Action Execution')",
            "required_data_sources": ["id1", "id2"],
            "required_mcp_tools": ["mcp_tool_name_1"]
        }}

        USER_QUESTION: {prompt}
        """

        # validate context length 
        valid = await self.validate_context_length(diagnosis_prompt)
        if not valid:
            raise ValueError("Prompt exceeds maximum context length")

        llm_instance = self.get_llama_idx_instance()
        response = await llm_instance.acomplete(diagnosis_prompt)

        try:
            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:-3]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:-3]
            return json.loads(raw_text.strip())
        except Exception as e:
            raise ValueError(f"Failed to parse diagnosis JSON: {e}. Response was: {response.text}")



    ###############
    # Abstract methods that must be implemented by all LLM providers
    ###############

    @property
    @abstractmethod
    def model_name(self) -> str:
        """
        Return the model name of the current configured LLM 
        """
        raise NotImplementedError("Subclasses must implement model_name property")

    @property 
    @abstractmethod
    def provider(self) -> str:
        """
        Return the provider name of the current configured LLM 
        """
        raise NotImplementedError("Subclasses must implement provider property")
    
    @property
    @abstractmethod
    def tokenizer(self) -> Callable[[str], list[int]]:
        """
        Return tokenizer for the current configured LLM
        """
        raise NotImplementedError("Subclasses must implement tokenizer property")


    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the LLM is available
        """
        raise NotImplementedError("Subclasses must implement is_available method.")

    @abstractmethod
    async def get_max_context_length(self) -> int:
        """
        Return the maximum context length for the LLM (taking into considerations potential hardware limitations if applicable).
        """
        raise NotImplementedError("Subclasses must implement get_max_context_length method.")

    @abstractmethod
    async def tokenize(self, text: str) -> list[int]:
        """
        Tokenize the input text using the tokenizer corresponding to the LLM and return list of tokens.
        """
        raise NotImplementedError("Subclasses must implement tokenize method.")

    @abstractmethod
    def get_llama_idx_instance(self, callback_manager: CallbackManager | None = None) -> FunctionCallingLLM:
        """
        Get the underlying LlamaIndex LLM instance.
        """
        raise NotImplementedError("Subclasses must implement get_llama_idx_instance method.")


    
    
