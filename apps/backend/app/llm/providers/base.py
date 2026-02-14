from abc import ABC, abstractmethod
from typing import Callable

from llama_index.core.llms.function_calling import FunctionCallingLLM


class LLMBase(ABC):

    ###############
    # Generic functionality that can be used by all LLM providers
    ###############

    async def send_message(self, prompt: str):
        """
        Send a message to the LLM and return the response
        """

        valid, _ = await self.validate_context_length(prompt)

        # validate context length 
        if not valid:
            raise ValueError("Prompt exceeds maximum context length")

        
        llm_instance = self.get_llama_idx_instance()
        return llm_instance.complete(prompt)


    
    async def validate_context_length(self, prompt: str, current_token_count: int = 0) -> tuple[bool, int]:
        """
        Validate that the current token count does not exceed the maximum context length.

        Returns:
            tuple[bool, int]: A tuple containing a boolean indicating if the prompt is valid and an integer representing the total token count.

        Args:
            prompt (str): The prompt to validate.
            current_token_count (int): The current token count (i.e if conversation history maintained)
        """
        # get max context length of model
        max_tokens = await self.get_max_context_length() #TODO: This accounts for strictly user input tokens, but should account for both

        total_input_tokens = await self.tokenize(prompt)
        
        return len(total_input_tokens) + current_token_count <= max_tokens, len(total_input_tokens) + current_token_count


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
    def decompose_query(self, query: str) -> list[str]:
        """
        Decompose a complex query into simpler sub-queries that can be answered individually.
        """
        raise NotImplementedError("Subclasses must implement decompose_query method.")
    

    @abstractmethod
    def get_llama_idx_instance(self) -> FunctionCallingLLM:
        """
        Get the underlying LlamaIndex LLM instance.
        """
        raise NotImplementedError("Subclasses must implement get_llama_idx_instance method.")


    
    
