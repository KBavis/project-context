from __future__ import annotations

from app.core.config import settings
from app.llm.providers.base import LLMBase

import logging

logger = logging.getLogger(__name__)

class LLMManager:


    def __init__(self, provider: str = settings.LL_MODEL_PROVIDER, model_name: str = settings.LL_MODEL, lazy_init: bool = False):
        self.provider = provider
        self.model_name = model_name

        # initialize LLM's
        self.llm = self._initialize_llm() if not lazy_init else None
        self._lightweight_llm = self._initialize_lightweight_llm() if not lazy_init else None
    

    def _initialize_lightweight_llm(self) -> LLMBase | None:
        """
        Initialize a lightweight LLM instance when ``LIGHTWEIGHT_LLM_MODEL``
        is configured and differs from the primary model.  Returns ``None``
        when no separate lightweight model is needed.
        """
        lightweight_model = settings.LIGHTWEIGHT_LLM_MODEL
        if not lightweight_model or lightweight_model == self.model_name:
            return None

        logger.debug(
            "Initializing lightweight LLM: provider=%s model=%s",
            self.provider, lightweight_model,
        )
        return self._initialize_llm(model_override=lightweight_model)


    def _initialize_llm(self, model_override: str | None = None):
        """
        Initialize the LLM based on the specified provider and model name.

        Args:
            model_override: If provided, use this model name instead of self.model_name.
                            Used to create the lightweight LLM instance.
        """
        model = model_override or self.model_name

        match self.provider.lower():
            case "ollama":
                from app.llm.providers.ollama import OllamaLLM
                llm = OllamaLLM(model_name=model)
                if not llm.is_available(): # TODO: Check if Ollaam from llama index has built in functionality to check this already 
                    raise ValueError(f"Ollama LLM with model '{model}' is not available. Please ensure Ollama is installed and the model is pulled locally.")
                return llm
            case "openai":
                from app.llm.providers.openai import OpenAIProvider
                llm = OpenAIProvider(model_name=model)
                if not llm.is_available(): 
                    raise ValueError(f"OpenAI LLM with model '{model}' is not available. Please ensure the OPENAI_API_KEY environment variable is set and the model name is valid.")
                return llm
            case "azure":
                from app.llm.providers.azure import AzureProvider
                llm = AzureProvider(model_name=model)
                if not llm.is_available():
                    raise ValueError(f"Azure LLM with model '{model}' is not available. Please ensure the AZURE_OPENAI_API_BASE and AZURE_API_KEY environment variables are set and the model name is valid.")
                return llm
            case _:
                raise ValueError(f"Unsupported LLM provider: {self.provider}")
    


    def get_llm(self, provider: str | None = None, model_name: str | None = None) -> LLMBase:
        """
        Get the currently initalized LLM instance 
        Initalize the LLM if not already initalized 

        Args:
            provider (str): provider to use for LLM
            model_name (str): model name to use for LLM
        """

        # update provider and model name if specified and re-initialize LLM
        if provider is not None and model_name is not None:
            self.provider = provider
            self.model_name = model_name
            self.llm = self._initialize_llm()

        # ensure LLM is initialized
        if self.llm is None:
            self.llm = self._initialize_llm()

        return self.llm

    def get_lightweight_llm(self) -> LLMBase:
        """
        Return the lightweight LLM instance for fast, inexpensive tasks
        (e.g. question diagnosis).

        If ``LIGHTWEIGHT_LLM_MODEL`` is configured, returns the dedicated
        lightweight instance.  Otherwise falls back to the primary LLM.
        """
        return self._lightweight_llm or self.get_llm()
