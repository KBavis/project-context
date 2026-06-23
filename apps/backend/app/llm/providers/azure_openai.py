from __future__ import annotations
from app.llm.providers.base import LLMBase
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.core.callbacks import CallbackManager

from typing import Callable
from app.core import settings


class AzureOpenAIProvider(LLMBase):
    """
    Provider for Azure-native OpenAI-compatible gateways.

    Encodes the Azure dialect (api-key header, api-version query, and the
    `/openai/deployments/<model>` URL path) rather than a model vendor. The
    deployment name is treated as equal to the model name.
    """

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
        return "AzureOpenAI"

    @property
    def tokenizer(self) -> Callable[[str], list[int]]:
        """
        Returns the tokenizer to be used for the LLM.
        """
        return self._resolve_tiktoken_encoder(self.model_name)

    def is_available(self) -> bool:
        """
        Check if the Azure OpenAI LLM is available

        TODO: Ping AzureOpenAI endpoint and check if model is available 
        """
        return settings.LLM_API_BASE is not None and settings.OPENAI_API_KEY is not None

    async def tokenize(self, text: str) -> list[int]:
        """
        Returns the token IDs for the given text.
        """
        return self.tokenizer(text)

    async def get_max_context_length(self) -> int:
        """
        Returns the maximum context length for the Azure OpenAI model.
        """
        azure_instance = self.get_llama_idx_instance()
        return azure_instance.metadata.context_window - settings.LLM_EXPECTED_RESPONSE_SIZE

    def get_llama_idx_instance(self, callback_manager: CallbackManager | None = None) -> AzureOpenAI:
        """
        Returns the LlamaIndex instance for the Azure OpenAI model.

        azure_endpoint must stop before the `/openai` segment; the client appends
        `/openai/deployments/<engine>/...?api-version=<api_version>`.

        max_retries: automatically retries on 429 rate-limit and 5xx errors with
        exponential backoff (handled by the underlying openai-python client).
        timeout: caps individual requests so a hung call doesn't block the workflow.
        """

        # the deployment (engine) may differ from the model name when the gateway exposes a model under
        # different deployment id (see LLM_AZURE_DEPLOYMENT_MAP)
        deployment = settings.LLM_AZURE_DEPLOYMENT_MAP.get(self.model_name, self.model_name)

        return AzureOpenAI(
            model=self.model_name,
            engine=deployment,            # deployment id used for URL routing; may differ from model name
            azure_endpoint=settings.LLM_API_BASE,
            api_version=settings.LLM_API_VERSION,
            api_key=settings.OPENAI_API_KEY,
            callback_manager=callback_manager,
            max_retries=6,       # retries: ~2min total backoff window on sustained 429s
            timeout=120.0,       # seconds before a single request is considered hung
        )
