from __future__ import annotations
from app.llm.providers.base import LLMBase
from llama_index.llms.openai import OpenAI
from llama_index.core.callbacks import CallbackManager

from typing import Callable
from app.core import settings


class OpenAIProvider(LLMBase):
    
    def __init__(self, model_name: str):
        self._model_name = model_name

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
        return self._resolve_tiktoken_encoder(self.model_name)

    
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
        

    def get_llama_idx_instance(self, callback_manager: CallbackManager | None = None) -> OpenAI:
        """
        Returns the LlamaIndex instance for the OpenAI model.

        max_retries: automatically retries on 429 rate-limit and 5xx errors with
        exponential backoff (handled by the underlying openai-python client).
        timeout: caps individual requests so a hung call doesn't block the workflow.
        """

        return OpenAI(
            model=self.model_name,
            api_key=settings.OPENAI_API_KEY,
            callback_manager=callback_manager,
            max_retries=6,       # retries: ~2min total backoff window on sustained 429s
            timeout=120.0,       # seconds before a single request is considered hung
        ) 
    


    

    
