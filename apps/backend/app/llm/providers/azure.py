from __future__ import annotations
from app.llm.providers.base import LLMBase
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.llms.openai_like import OpenAILike
from llama_index.core.callbacks import CallbackManager
from llama_index.core.llms.function_calling import FunctionCallingLLM

from typing import Any, Callable
from app.core import settings


class GatewayOpenAILike(OpenAILike):
    """
    "OpenAILike" client for using the Azure provider as a multi-vendor gateway.

    Assumes non-OpenAI models (e.g. Claude) are reachable over an
    OpenAI-compatible "/chat/completions" endpoint. Such gateways often
    translate imperfectly to/from the underlying vendor, so this subclass
    patches the request/response stream to keep LlamaIndex happy. Each fix is a
    no-op against a conformant endpoint and can be removed once the gateway
    behaves.
    """

    @staticmethod
    def _coerce_empty_tool_call_args(kwargs: Any) -> None:
        """
        Coerce empty tool-call "arguments" ("") to "{}" on outgoing
        messages. A no-arg tool call sent as "" can't be translated into a
        vendor tool-input object, so the gateway rejects the request.
        """
        for message in kwargs.get("messages") or []:
            if not isinstance(message, dict):
                continue
            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                if function is not None and function.get("arguments") == "":
                    function["arguments"] = "{}"

    @staticmethod
    def _sanitize_chunk(chunk: Any, tool_index: int) -> int:
        """
        Fix a streaming chunk in place and return the running tool-call index.

        Guards two gateway quirks: a "choices=None" chunk (which LlamaIndex
        would choke on) is coerced to "[]", and parallel tool calls that the
        gateway mislabels with the same index are re-indexed (each delta
        carrying an "id" starts a new call) so distinct calls aren't merged.
        """
        if chunk.choices is None:
            chunk.choices = []
        for choice in chunk.choices:
            delta = getattr(choice, "delta", None)
            for tool_call in (getattr(delta, "tool_calls", None) or []) if delta else []:
                if getattr(tool_call, "id", None):
                    tool_index += 1
                if tool_index >= 0:
                    tool_call.index = tool_index
        return tool_index

    def _get_aclient(self) -> Any:
        """
        Return the async OpenAI client with its "chat.completions.create"
        wrapped to apply the gateway fixes: outgoing requests are patched by
        "_coerce_empty_tool_call_args", and streamed responses by
        "_sanitize_chunk". The wrap is applied once (guarded by
        "_gateway_safe") since LlamaIndex may reuse the same client.
        """
        client = super()._get_aclient()
        completions = client.chat.completions
        if not getattr(completions, "_gateway_safe", False):
            original_create = completions.create

            async def create(*args: Any, **kwargs: Any) -> Any:
                self._coerce_empty_tool_call_args(kwargs)
                result = await original_create(*args, **kwargs)
                if not kwargs.get("stream"):
                    return result

                async def sanitized() -> Any:
                    tool_index = -1
                    async for chunk in result:
                        tool_index = self._sanitize_chunk(chunk, tool_index)
                        yield chunk

                return sanitized()

            completions.create = create
            completions._gateway_safe = True
        return client

    def _get_client(self) -> Any:
        """
        Synchronous counterpart of `_get_aclient`: return the OpenAI client
        with "chat.completions.create" wrapped so the same gateway request and
        streaming fixes are applied to non-async calls.
        """
        client = super()._get_client()
        completions = client.chat.completions
        if not getattr(completions, "_gateway_safe", False):
            original_create = completions.create

            def create(*args: Any, **kwargs: Any) -> Any:
                self._coerce_empty_tool_call_args(kwargs)
                result = original_create(*args, **kwargs)
                if not kwargs.get("stream"):
                    return result

                def sanitized() -> Any:
                    tool_index = -1
                    for chunk in result:
                        tool_index = self._sanitize_chunk(chunk, tool_index)
                        yield chunk

                return sanitized()

            completions.create = create
            completions._gateway_safe = True
        return client


class AzureProvider(LLMBase):
    """
    Provider for Azure-hosted models. Supports plain Azure OpenAI usage and,
    when `AZURE_MULTI_VENDOR_GATEWAY` is enabled, using Azure as a gateway to
    other vendors (e.g. Claude). One provider serves every model; the model name
    selects the vendor and the route (Azure OpenAI deployments vs. the gateway's
    "/v1/chat/completions" endpoint).

    TODO: Gemini is not offered yet - streaming is currently broken on the
    configured endpoint.
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
        Returns the model vendor family (OpenAI, Anthropic, Google) based on model name.
        """
        model_lower = self.model_name.lower()
        if "gpt" in model_lower or model_lower.startswith(("o1", "o3", "o4")):
            return "OpenAI"
        elif "claude" in model_lower:
            return "Anthropic"
        elif "gemini" in model_lower:
            return "Google"
        return "Unknown"

    @property
    def tokenizer(self) -> Callable[[str], list[int]]:
        return self._resolve_tiktoken_encoder(self.model_name)

    def is_openai_model(self) -> bool:
        """
        OpenAI models (GPT/o-series) run on `AzureOpenAI` via the Azure
        "/openai/deployments" route; every other vendor runs on `OpenAILike`
        via the "/v1/chat/completions" route.
        """
        return self.vendor == "OpenAI"

    def is_available(self) -> bool:
        """
        Check if the Azure gateway is reachable.
        Check that the gateway base URL and key required for this model's route
        are configured.

        TODO: Ping the Azure endpoint and verify the deployment exists.
        """
        if settings.AZURE_API_KEY is None:
            return False
        if self.is_openai_model():
            return settings.AZURE_OPENAI_API_BASE is not None
        # Non-OpenAI vendors (Claude/Gemini) are only reachable when the Azure
        # endpoint is configured as a multi-vendor gateway.
        return settings.AZURE_MULTI_VENDOR_GATEWAY and settings.AZURE_STANDARD_API_BASE is not None

    async def tokenize(self, text: str) -> list[int]:
        return self.tokenizer(text)

    async def get_max_context_length(self) -> int:
        """
        Returns the maximum context length for the Azure-hosted model.
        """
        azure_instance = self.get_llama_idx_instance()
        return azure_instance.metadata.context_window - settings.LLM_EXPECTED_RESPONSE_SIZE

    def get_llama_idx_instance(self, callback_manager: CallbackManager | None = None) -> FunctionCallingLLM:
        """
        Build the LlamaIndex client for the current model:
        - GPT/o-series -> `AzureOpenAI` ("/openai/deployments" route, api-key header, api-version query).
        - Gemini/Claude -> "OpenAILike" ("/v1/chat/completions" route, Bearer auth).
        """
        if self.is_openai_model():
            return self._build_azure_openai_instance(callback_manager)
        return self._build_openai_like_instance(callback_manager)

    def _build_openai_like_instance(self, callback_manager: CallbackManager | None = None) -> FunctionCallingLLM:
        """
        Build an "OpenAILike" client (Gemini/Claude) for the
        ``AZURE_STANDARD_API_BASE``-hosted ``/v1/chat/completions`` route.

        This route is only reachable when `AZURE_MULTI_VENDOR_GATEWAY` is
        enabled (see `is_available`), so it always uses ``GatewayOpenAILike``.
        """
        return GatewayOpenAILike(
            model=self.model_name,
            api_base=f"{settings.AZURE_STANDARD_API_BASE}/{self.model_name}/v1",
            api_key=settings.AZURE_API_KEY,
            is_chat_model=True,
            is_function_calling_model=True,
            context_window=settings.AZURE_CONTEXT_WINDOW_OVERRIDES.get(
                self.model_name, settings.AZURE_DEFAULT_CONTEXT_WINDOW
            ),
            callback_manager=callback_manager or CallbackManager([]),
            max_retries=6,       # retries: ~2min total backoff window on sustained 429s
            timeout=120.0,       # seconds before a single request is considered hung
        )

    def _build_azure_openai_instance(self, callback_manager: CallbackManager | None = None) -> AzureOpenAI:
        """
        Returns the LlamaIndex instance for an Azure-hosted OpenAI model.

        The deployment (engine) may differ from the model name when the gateway exposes a model under
        a different deployment id (see AZURE_OPENAI_DEPLOYMENT_MAP)
        """
        deployment = settings.AZURE_OPENAI_DEPLOYMENT_MAP.get(self.model_name, self.model_name)
        return AzureOpenAI(
            model=self.model_name,
            engine=deployment,            # deployment id used for URL routing; may differ from model name
            azure_endpoint=settings.AZURE_OPENAI_API_BASE,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            api_key=settings.AZURE_API_KEY,
            callback_manager=callback_manager,
            max_retries=6,       # retries: ~2min total backoff window on sustained 429s
            timeout=120.0,       # seconds before a single request is considered hung
        )
