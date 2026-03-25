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
    

    async def decompose_query(self, prompt: str, existing_messages: str) -> dict:
        """
        Decompose a complex query into simpler sub-queries that can be answered individually.

        Args:
            prompt (str): The prompt to decompose
            existing_messages (str): The existing messages in the conversation
        """

        # TODO: Add logic for ensuring that the question is sound or if we require additional clarification from user 

        try:

            decompose_query_prompt = f"""
                        TASK: You are a Query Decomposition Engine. Analyze the user's question and history to prepare search queries.

                        CRITICAL RULES:
                        1. **DO NOT answer the user's question yourself.** Your ONLY output should be a valid JSON plan.
                        2. If the answer is already fully contained in the conversation history, set "requires_retrieval": false and "queries": [].
                        3. Resolving Ambiguity: Turn fragmented questions like "What about that?" into standalone search queries based on previous context.
                        4. Output MUST be a single, strict JSON block.

                        OUTPUT_FORMAT:
                        {{
                            "requires_retrieval": boolean,
                            "queries": [
                                {{"query": "string"}}
                            ]
                        }}

                        EXAMPLES:
                        - History has the answer: {{"requires_retrieval": false, "queries": []}}
                        - More info needed: {{"requires_retrieval": true, "queries": [{{"query": "explanation of project implementation and architecture"}}]}}

                        USER_QUESTION: {prompt}
                        CONVERSATION_HISTORY (sender:<message>): {existing_messages}
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


    
    
