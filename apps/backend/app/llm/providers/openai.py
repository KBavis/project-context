from __future__ import annotations
from app.llm.providers.base import LLMBase
from llama_index.llms.openai import OpenAI

from typing import Callable
from app.core import settings


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
    def tokenizer(self) -> Callable[[str], list[int]]:
        """
        Returns the tokenizer to be used for the LLM.
        """
        tokenizer = self.get_llama_idx_instance()._tokenizer
        return tokenizer.encode if tokenizer else lambda x: []

    
    def is_available(self) -> bool:
        """
        Check if the Open AI LLM is available
        """

        return True # TODO: Implement me




    async def tokenize(self, text: str) -> list[int]:
        """
        Returns the token IDs for the given text.
        """

        return self.tokenizer(text)
    

    async def get_max_context_length(self) -> int:
        """
        Returns the maximum context length for the OpenAI model.
        """

        openai_instance = self.get_llama_idx_instance() 
        return openai_instance.metadata.context_window - settings.LLM_EXPECTED_RESPONSE_SIZE


    
    async def _get_model_stats(self):
        """
        Retrieve relevant model stats for OpenAI model
        """
        # NOTE: It would be nice to also store some pricing information in order to calculate cost per query
        

    def get_llama_idx_instance(self) -> OpenAI:
        """
        Returns the LlamaIndex instance for the OpenAI model.
        """

        return OpenAI(model=self.model_name, api_key=settings.OPEN_AI_API_KEY) # TODO: Setup additional configurations 
    


    

    
