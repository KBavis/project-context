from .base import LLMBase
from llama_index.llms.ollama import Ollama

class OllamaLLM(LLMBase):

    def __init__(self, model_name: str):
        self.model_name = model_name
    

    def get_max_context_length(self) -> int:
        """
        Return the maximum context length for the Ollama LLM.
        """

        return 2048  # TODO: Implement me and remove place holder value 
    
    def tokenize(self, text: str) -> list[str]:
        """
        Tokenize the input text using the Ollama tokenizer and return list of tokens.
        """

        # TODO: Implement me
    

    def decompose_query(self, query: str) -> list[str]:
        """
        Decompose a complex query into simpler sub-queries that can be answered individually.
        """
        # TODO: Implement me


    def is_available(self) -> bool:
        """
        Check if a) ollama is installed and b) the specified model is available.
        """
        # TODO: Implement me 
        return True
    

    def get_llama_idx_instance(self) -> Ollama:
        """
        Get the underlying LlamaIndex Ollama instance.
        """
        return Ollama(model=self.model_name) # TODO: Add additional configuration options as needed