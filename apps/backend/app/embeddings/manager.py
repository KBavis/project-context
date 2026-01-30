from app.core import settings
from app.models.collection import ChromaCollection
from app.embeddings.lru_cache import get_cached_embedding, cache_embedding

from transformers import AutoTokenizer
import logging
from typing import Dict
import asyncio
from uuid import UUID


class EmbeddingManager:

    def __init__(self, chroma_collections: Dict[str, ChromaCollection], project_id: UUID | None = None):

        # Coding Embedding Specific Values
        self._code_provider = chroma_collections["CODE"].embedding_provider 
        self._code_model = chroma_collections["CODE"].embedding_model  

        # Docs Embedding Specific Values
        self._docs_provider = chroma_collections["DOCS"].embedding_provider
        self._docs_model = chroma_collections["DOCS"].embedding_model
        
        # Project ID for caching
        self._project_id = project_id


    def get_embedding_model(self, source_type: str):
        """
        Retrieve the relevant embedding model to be utilize
        based on configurations and the specified source type
        """
        return (
            self.get_docs_embedding_model()
            if source_type == "DOCS"
            else self.get_code_embedding_model()
        )

    async def aget_embedding_model(self, source_type: str):
        """
        Asynchronously retrieve relevant embedding model 
        """
        return await asyncio.to_thread(self.get_embedding_model, source_type)
    
    async def aget_embedding_model_cached(self, source_type: str):
        """
        Asynchronously retrieve relevant embedding model with caching support.
        
        If project_id is set and the model is cached, returns the cached version.
        Otherwise, loads the model and caches it for future use.
        
        Args:
            source_type (str): Type of content ("DOCS" or "CODE")
            
        Returns:
            BaseEmbedding: The embedding model instance
        """
        cache_key = None
        
        # Generate cache key if project_id is available
        if self._project_id:
            cache_key = f"{self._project_id}:{source_type}"
            
            # Try to get from cache first
            cached_model = await get_cached_embedding(cache_key)
            if cached_model:
                return cached_model
        
        # Cache miss or no project_id - load the model
        model = await self.aget_embedding_model(source_type)
        
        # Cache it for next time if we have a project_id
        if cache_key:
            await cache_embedding(cache_key, model)
        
        return model

    
    def get_tokenizer(self, source_type):
        """
        Retrieve configured tokenizer based on configured models and provider 
        """

        return (
            self.get_docs_tokenizer()
            if source_type == "DOCS"
            else self.get_code_tokenizer()
        )
    
    def get_code_tokenizer(self):
        """
        Use Docling to retrieve code tokenizer corresponding to 
        configured model and provider 
        """

        match self._code_provider:

            case "HuggingFace":
                from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                return HuggingFaceTokenizer(
                    tokenizer=AutoTokenizer.from_pretrained(self._code_model)
                )
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._code_provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._code_provider}"
                )


    def get_docs_tokenizer(self):
        """
        Use Docling to retrieve docs tokenizer corresponding to 
        configured model and provider 
        """
        
        match self._docs_provider:

            case "HuggingFace":
                from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
                return HuggingFaceTokenizer(
                    tokenizer=AutoTokenizer.from_pretrained(self._docs_model)
                )
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._docs_provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._docs_provider}"
                )


    def get_docs_embedding_model(self):

        match self._docs_provider:

            # Local Embedding Providers
            case "HuggingFace":
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding

                return HuggingFaceEmbedding(model_name=settings.DOCS_EMBEDDING_MODEL)
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._docs_provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._docs_provider}"
                )


    def get_code_embedding_model(self):

        match self._code_provider:

            # Local Embedding Providers
            case "HuggingFace":
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding

                return HuggingFaceEmbedding(model_name=settings.CODE_EMBEDDING_MODEL)
            case _:
                logging.error(
                    f"The embedidng provider specified, '{self._code_provider}', is not curretly set up for this application"
                )
                raise Exception(
                    f"Invalid embedding provider specified: {self._code_provider}"
                )
