from app.llm.providers.base import LLMBase
import tiktoken
from llama_index.llms.openai import OpenAI
# import openai


class OpenAIProvider(LLMBase):
    
    def __init__(self, model_name: str):
        self._model_name = model_name

    # TODO: Add more models to this mapping
    context_lengths = {
        "gpt-4o-mini": 128000,
    }

    @property
    def model_name(self) -> str:
        """
        Returns the name of the model to be used for the LLM.
        """
        return self._model_name


    @property
    def provider(self) -> str:
        """
        Returns the name of the provider to be used for the LLM.
        """
        return "OpenAI"

    
    @property
    def tokenizer(self) -> tiktoken.Encoding:
        """
        Returns the tokenizer to be used for the LLM.
        """
        return tiktoken.get_encoding(self.model_name)


    async def tokenize(self, text: str) -> list[int]:
        """
        Returns the token IDs for the given text.
        """

        return self.tokenizer.encode(text)
    

    async def get_max_context_length(self) -> int:
        """
        Returns the maximum context length for the OpenAI model.
        """

        # TODO: Implement a scraping of https://platform.openai.com/docs/models to get the max context length for each model
        return self.context_lengths.get(self.model_name, 8192)

    
    async def _get_model_stats(self):
        """
        Retrieve relevant model stats for OpenAI model
        """
        # NOTE: It would be nice to also store some pricing information in order to calculate cost per query
        

    def decompose_query(self, query: str) -> list[str]:
        """
        Decompose a complex query into simpler sub-queries that can be answered individually.
        """

        #TODO: Implement me 
        return [query]


    def get_llama_idx_instance(self) -> object:
        """
        Returns the LlamaIndex instance for the OpenAI model.
        """

        return OpenAI(model=self.model_name) # TODO: Setup additional configurations 
    


    

    
