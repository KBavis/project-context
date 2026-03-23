from __future__ import annotations
from app.models.collection import ChromaCollection
from app.embeddings.lru_cache import get_cached_embedding, cache_embedding

import logging
import asyncio
from uuid import UUID


class EmbeddingManager:

    def __init__(self, chroma_collection: ChromaCollection, project_id: UUID | None = None):


        self._provider = chroma_collection.embedding_provider
        self._model = chroma_collection.embedding_model
        
        # Project ID for caching
        self._project_id = project_id


    async def aget_embedding_model(self):
        """
        Asynchronously retrieve relevant embedding model 
        """
        return await asyncio.to_thread(self.get_embedding_model)

    
    async def aget_embedding_model_cached(self):
        """
        Asynchronously retrieve relevant embedding model with caching support.
        
        If project_id is set and the model is cached, returns the cached version.
        Otherwise, loads the model and caches it for future use.
            
        Returns:
            BaseEmbedding: The embedding model instance
        """
        cache_key = None
        
        # Generate cache key if project_id is available
        if self._project_id:
            cache_key = f"{self._project_id}:{self._model}"
            
            # Try to get from cache first
            cached_model = await get_cached_embedding(cache_key)
            if cached_model:
                return cached_model
        
        # Cache miss or no project_id - load the model
        model = await self.aget_embedding_model()
        
        # Cache it for next time if we have a project_id
        if cache_key:
            await cache_embedding(cache_key, model)
        
        return model


    def get_embedding_model(self):

        match self._provider:

            # Local Embedding Providers
            case "HuggingFace":
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding

                return HuggingFaceEmbedding(model_name=self._model)
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._provider}"
                )


    def get_tokenizer(self):
        """
        Retrieve the Tokenizer corresponding to our Embeddings for Docling chunking 

        TODO: Determine if we can do something similar for Code chunking 
        """
        
        match self._provider:

            case "HuggingFace":
                from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                from transformers import AutoTokenizer
                return HuggingFaceTokenizer(
                    tokenizer=AutoTokenizer.from_pretrained(self._model)
                )
            case _:
                logging.error(
                    f"The embedding provider specified, '{self._provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._provider}"
                )
