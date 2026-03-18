from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable
import json

from llama_index.core.llms.function_calling import FunctionCallingLLM


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
        return llm_instance.complete(prompt)


    
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
    

    async def decompoGse_query(self, prompt: str, existing_messages: str) -> dict:
        """
        Decompose a complex query into simpler sub-queries that can be answered individually.

        Args:
            prompt (str): The prompt to decompose
            existing_messages (str): The existing messages in the conversation
        """

        # TODO: Add logic for ensuring that the question is sound or if we require additional clarification from user 

        try:

            decompose_query_prompt = f"""
                        You are a query decomposition and routing assistant. Analyze the user's question using the conversation history and return a structured JSON result.

                        AVAILABLE COLLECTION DATA: 
                            - markdown documentation, guides, conceptual explanations, API references, source code files, function definitions, implementation examples

                        MESSAGES FORMAT: "sender:<message>", ordered oldest to latest.

                        YOUR TASKS:
                        1. Resolve any ambiguous or incomplete questions using conversation history (e.g. "What about projects?" → "How are projects created?" based on prior context).
                        2. Determine if the question requires retrieving new context, or can be answered from existing messages alone.
                        3. If new context is needed, decompose the query if necessary and assign each sub-query to the appropriate collection(s).

                        RULES:
                        - Return "requires_retrieval": false ONLY if you are highly confident the question can be fully answered from existing messages. When in doubt, set to true.
                        - Only decompose when sub-topics would likely live in different documents or sections. Do not split unnecessarily.
                        - Each sub-query should be self-contained and independently retrievable.

                        OUTPUT FORMAT (strict JSON, no extra text):
                        {{
                            "requires_retrieval": true | false,
                            "queries": [
                                {{"query": "<resolved_query>"}},
                                {{"query": "<resolved_query2>" }}
                            ]
                        }}

                        - If "requires_retrieval" is false, return an empty queries array.
                        - "queries" must always have at least one entry when requires_retrieval is true.

                        User Question: {prompt}
                        Existing Messages: {existing_messages}
            """

            # validate context length 
            valid = await self.validate_context_length(decompose_query_prompt)
            if not valid:
                raise ValueError("Prompt exceeds maximum context length")

            llm_instance = self.get_llama_idx_instance()
            response = await llm_instance.acomplete(decompose_query_prompt)

            return json.loads(response.text)
        
        except Exception as e:
            raise ValueError(f"Failed to decompose query: {e}")

        



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
    def get_llama_idx_instance(self) -> FunctionCallingLLM:
        """
        Get the underlying LlamaIndex LLM instance.
        """
        raise NotImplementedError("Subclasses must implement get_llama_idx_instance method.")


    
    
