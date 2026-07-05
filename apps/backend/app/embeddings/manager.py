from __future__ import annotations
from app.embeddings.lru_cache import get_cached_embedding, cache_embedding
from app.core import settings

import logging
import asyncio
from typing import Callable


class EmbeddingManager:

    @classmethod
    async def aget_embedding_model(cls):
        """
        Asynchronously retrieve relevant embedding model 
        """
        return await asyncio.to_thread(cls.get_embedding_model)

    
    @classmethod
    async def aget_embedding_model_cached(cls):
        """
        Asynchronously retrieve relevant embedding model with caching support.
        
        Loads the model and caches it for future use.
            
        Returns:
            BaseEmbedding: The embedding model instance
        """
        cache_key = settings.EMBEDDING_MODEL
        
        # try to get from cache first
        cached_model = await get_cached_embedding(cache_key)
        if cached_model:
            return cached_model
        
        # cache miss - load the model
        model = await cls.aget_embedding_model()
        
        # cache it for next time
        await cache_embedding(cache_key, model)
        
        return model


    @classmethod
    def get_embedding_model(cls):

        match settings.EMBEDDING_PROVIDER:

            # Local Embedding Providers
            case "HuggingFace":
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding

                class CachedHuggingFaceEmbedding(HuggingFaceEmbedding):
                    def __deepcopy__(self, memo):
                        # Workaround: LlamaIndex's QueryFusionRetriever attempts to deepcopy retrievers,
                        # which crashes PyTorch when encountering meta tensors from HuggingFace accelerate.
                        # Returning `self` avoids the crash and prevents duplicating the model in RAM.
                        return self

                return CachedHuggingFaceEmbedding(
                    model_name=settings.EMBEDDING_MODEL,
                    embed_batch_size=settings.EMBEDDING_BATCH_SIZE,
                    device="cuda" if settings.DOCLING_ACCELERATOR_DEVICE == "cuda" else None
                )

            # Hosted Azure-native OpenAI-compatible Embedding Providers
            case "Azure":
                from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding

                return AzureOpenAIEmbedding(
                    model=settings.EMBEDDING_MODEL,
                    deployment_name=settings.EMBEDDING_MODEL,  # deployment name is treated as equal to the model name
                    azure_endpoint=settings.EMBEDDING_API_BASE,
                    api_version=settings.EMBEDDING_API_VERSION,
                    api_key=settings.AZURE_API_KEY,
                    embed_batch_size=settings.EMBEDDING_BATCH_SIZE,
                    num_workers=settings.EMBEDDING_NUM_WORKERS,  # concurrent embedding requests (with use_async index build)
                )
            case _:
                logging.error(
                    f"The embedidng provider specified, '{settings.EMBEDDING_PROVIDER}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {settings.EMBEDDING_PROVIDER}"
                )


    @classmethod
    def get_tokenizer(cls):
        """
        Retrieve the Tokenizer corresponding to our Embeddings for Docling chunking.
        
        The tokenizer's `max_tokens` is the Docling chunker's target chunk size
        (CHUNK_TARGET_TOKENS) - deliberately well below the embedding model's
        hard limit so chunks stay semantically coherent.
        
        TODO: Determine if we can do something similar for Code chunking
        """
        
        match settings.EMBEDDING_PROVIDER:

            case "HuggingFace":
                from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                from transformers import AutoTokenizer
                return HuggingFaceTokenizer(
                    tokenizer=AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL),
                    max_tokens=settings.CHUNK_TARGET_TOKENS,
                )
            case "Azure":
                import tiktoken
                from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
                return OpenAITokenizer(
                    tokenizer=tiktoken.encoding_for_model(settings.EMBEDDING_MODEL),
                    max_tokens=settings.CHUNK_TARGET_TOKENS,
                )
            case _:
                logging.error(
                    f"The embedding provider specified, '{settings.EMBEDDING_PROVIDER}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {settings.EMBEDDING_PROVIDER}"
                )

    @classmethod
    def get_token_encode_fn(cls) -> Callable[[str], list[int]]:
        """
        Return the raw encode function for the configured embedding model's tokenizer.
        
        Reuses the same tokenizer as Docling chunking so token counts match, and is
        used to measure/bound chunk sizes against the embedding model's token limit.
        
        # the underlying encoder (tiktoken Encoding / HF tokenizer) exposed by the
        # Docling tokenizer wrapper; both provide an `.encode(text) -> list[int]`
        """
        return cls.get_tokenizer().tokenizer.encode
