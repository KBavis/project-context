from __future__ import annotations
from app.embeddings.lru_cache import get_cached_embedding, cache_embedding
from app.core import settings

import logging
import asyncio


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

                return CachedHuggingFaceEmbedding(model_name=settings.EMBEDDING_MODEL)
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
        Retrieve the Tokenizer corresponding to our Embeddings for Docling chunking 

        TODO: Determine if we can do something similar for Code chunking 
        """
        
        match settings.EMBEDDING_PROVIDER:

            case "HuggingFace":
                from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                from transformers import AutoTokenizer
                return HuggingFaceTokenizer(
                    tokenizer=AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL)
                )
            case _:
                logging.error(
                    f"The embedding provider specified, '{settings.EMBEDDING_PROVIDER}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {settings.EMBEDDING_PROVIDER}"
                )
