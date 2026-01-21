from abc import ABC, abstractmethod
from transformers import AutoTokenizer


class LLMBase(ABC):

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
    def tokenizer(self) -> AutoTokenizer:
        """
        Return tokenizer for the current configured LLM
        """
        raise NotImplementedError("Subclasses must implement tokenizer property")


    @abstractmethod
    async def get_max_context_length(self) -> int:
        """
        Return the maximum context length for the LLM (taking into considerations potential hardware limitations if applicable).
        """
        raise NotImplementedError("Subclasses must implement get_max_context_length method.")

    @abstractmethod
    async def tokenize(self, text: str) -> list[str]:
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
    def get_llama_idx_instance(self) -> object:
        """
        Get the underlying LlamaIndex LLM instance.
        """
        raise NotImplementedError("Subclasses must implement get_llama_idx_instance method.")


    
    
