from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable
import json
import logging

import tiktoken
from llama_index.core.llms.function_calling import FunctionCallingLLM
from llama_index.core.callbacks import CallbackManager

from app.core import settings

logger = logging.getLogger(__name__)


class LLMBase(ABC):

    ###############
    # Generic functionality that can be used by all LLM providers
    ###############

    def _resolve_tiktoken_encoder(self, model_name: str) -> Callable[[str], list[int]]:
        """
        Return a tiktoken `.encode` callable for the given OpenAI model name.

        Fall back to a known encoding when tiktoken doesn't recognize the
        specified model.

        Args:
            model_name (str): The OpenAI model name to resolve an encoder for.
        """
        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            encoding = tiktoken.get_encoding(settings.OPENAI_FALLBACK_TIKTOKEN_ENCODING)
            logger.debug(
                "tiktoken has no mapping for model '%s'; falling back to encoding '%s'",
                model_name,
                settings.OPENAI_FALLBACK_TIKTOKEN_ENCODING,
            )
        return encoding.encode

    async def send_message(self, prompt: str, temperature: float | None = None):
        """
        Send a message to the LLM and return the response

        Args:
            prompt (str): The prompt to send to the LLM
            temperature (float | None): Optional sampling temperature override for this call
        """

        valid = await self.validate_context_length(prompt)

        # validate context length 
        if not valid:
            raise ValueError("Prompt exceeds maximum context length")

        
        llm_instance = self.get_llama_idx_instance()
        if temperature is not None:
            # LlamaIndex LLM clients expose a mutable `temperature`; ignore if unsupported.
            try:
                llm_instance.temperature = temperature
            except Exception:
                logger.debug("LLM instance does not support a temperature override; using default.")
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
        mcp_tools_info: str,
        conversation_history_str: str = "",
        project_context: str = ""
    ) -> dict:
        """
        Phase 1: Diagnosis. Analyze the user's question against available data sources and tools to determine the 
        optimal research trajectory and filter out unnecessary context.
        """
        diagnosis_prompt = f"""
        TASK: You are the Diagnosis Agent for a coding assistant workflow. 
        Your job is to analyze the USER_QUESTION and CONVERSATION_HISTORY to determine exactly what the user is asking, classify the question type, and determine which MCP Tools are necessary to answer it.

        PROJECT CONTEXT (the project this conversation is scoped to):
        {project_context}

        CONVERSATION_HISTORY:
        {conversation_history_str}

        AVAILABLE DATA SOURCES:
        {data_sources_info}

        AVAILABLE INTERNAL TOOLS (Always active, do not select these, they are provided for context so you know what base capabilities exist):
        {internal_tools_info}

        AVAILABLE MCP TOOLS (External connections, mapped by Data Source ID):
        {mcp_tools_info}

        CRITICAL RULES:
        1. Read the PROJECT CONTEXT and CONVERSATION_HISTORY to resolve any ambiguities in the USER_QUESTION (e.g., identifying what "it", "this file", or "this project" refers to).
        2. "refined_question": A standalone version of the user's prompt with all ambiguities resolved. You must retain the original core intent and technical constraints of the user's question, only injecting the missing context.
        3. "required_mcp_tools": A dictionary mapping a Data Source ID to a list of MCP Tool Names. ONLY select MCP tools that belong to the Data Sources listed above. ONLY include an MCP tool if the Internal Tools cannot accomplish the task. If no MCP tools are needed, return an empty dictionary.
        4. "research_depth": How much INVESTIGATION is needed to answer accurately. This is about research EFFORT, not how long the answer should be. Choose exactly one:
           - "shallow": a single fact, definition, or location; or an explicitly high-level / overview / brief request (e.g. "what does the X permission do?", "where is Y configured?", "give me a high-level overview"). A couple of targeted lookups suffice.
           - "deep": ONLY for explicitly EXHAUSTIVE requests that must cover many files/components - e.g. "find ALL discrepancies between docs and code", "audit every endpoint", "explain everything about X in full detail". If the word "all"/"every"/"exhaustive"/"comprehensive" (or a clear equivalent) is not present, it is almost never "deep".
           - "standard": anything in between, and the DEFAULT whenever effort is ambiguous. A SPECIFIC question about one behavior, flow, endpoint, or validation - e.g. "what happens when banking info is not provided?", "how is X validated?" - is "standard" even if answering it requires reading a few files.
           IMPORTANT: breadth of SUBJECT does not imply deep research. A broad topic asked at a high level (e.g. "high-level overview of the whole project") is "shallow" or "standard", not "deep". Prefer "standard" over "deep" when unsure - over-classifying as "deep" wastes a large amount of time.
        5. Your ONLY output MUST be a valid JSON object. Do NOT wrap it in markdown block quotes.

        OUTPUT_FORMAT:
        {{
            "user_intent": "What the user is actually trying to accomplish.",
            "contextual_clarification": "How the conversation history resolves ambiguity.",
            "refined_question": "Standalone version of the prompt.",
            "question_type": "Classification of the question (e.g. 'Deep Research', 'General Inquiry', 'Action Execution')",
            "research_depth": "shallow | standard | deep",
            "mcp_tool_reasoning": "Brief explanation of which MCP tools are needed, ensuring they ONLY belong to the available data sources.",
            "required_mcp_tools": {{
                "id1": ["mcp_tool_name_1"]
            }}
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


    
    
