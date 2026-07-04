from __future__ import annotations
from app.llm.providers.base import LLMBase
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.core.callbacks import CallbackManager

from typing import Callable
from app.core import settings


class AzureProvider(LLMBase):
    """
    General-purpose provider for Azure-hosted model gateways.

    Routes all models (OpenAI GPT, Anthropic Claude, Google Gemini, etc.)
    through the Azure OpenAI-compatible chat/completions wire format.
    The gateway dialect (api-key header, api-version query, and the
    ``/openai/deployments/<model>`` URL path) is model-vendor-agnostic;
    adding a new model is a config/list change, not a new class.

    The deployment name is resolved via ``LLM_AZURE_DEPLOYMENT_MAP`` and
    falls back to the model name itself.
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
        return "Azure"

    @property
    def vendor(self) -> str:
        """
        Returns the model vendor family (OpenAI, Anthropic, Google) based on model name prefix.
        """
        model_lower = self.model_name.lower()
        if "gpt" in model_lower:
            return "OpenAI"
        elif "claude" in model_lower:
            return "Anthropic"
        elif "gemini" in model_lower:
            return "Google"
        return "Unknown"

    @property
    def tokenizer(self) -> Callable[[str], list[int]]:
        """
        Returns the tokenizer to be used for the LLM.

        NOTE: tiktoken is an approximation for non-OpenAI models
        (Claude, Gemini). This is acceptable for the "does it fit?"
        guard but token counts will not be exact.
        """
        return self._resolve_tiktoken_encoder(self.model_name)

    def is_available(self) -> bool:
        """
        Check if the Azure gateway is reachable.

        TODO: Ping the Azure endpoint and verify the deployment exists.
        """
        return settings.LLM_API_BASE is not None and settings.AZURE_API_KEY is not None

    async def tokenize(self, text: str) -> list[int]:
        """
        Returns the token IDs for the given text.
        """
        return self.tokenizer(text)

    async def get_max_context_length(self) -> int:
        """
        Returns the maximum context length for the Azure-hosted model.
        """
        azure_instance = self.get_llama_idx_instance()
        return azure_instance.metadata.context_window - settings.LLM_EXPECTED_RESPONSE_SIZE

    def get_llama_idx_instance(self, callback_manager: CallbackManager | None = None) -> AzureOpenAI:
        """
        Returns the LlamaIndex instance for the Azure-hosted model.

        azure_endpoint must stop before the ``/openai`` segment; the client
        appends ``/openai/deployments/<engine>/...?api-version=<api_version>``.

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
            api_key=settings.AZURE_API_KEY,
            callback_manager=callback_manager,
            max_retries=6,       # retries: ~2min total backoff window on sustained 429s
            timeout=120.0,       # seconds before a single request is considered hung
        )
