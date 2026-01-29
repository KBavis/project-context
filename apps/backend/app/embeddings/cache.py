from typing import Dict
from uuid import UUID
from llama_index.core.embeddings import BaseEmbedding
import logging
import asyncio

logger = logging.getLogger(__name__)

# Module-level cache for embedding models
# This acts as a singleton across the application
_embedding_cache: Dict[str, BaseEmbedding] = {}
_cache_lock = asyncio.Lock()


def get_cached_embedding(cache_key: str) -> BaseEmbedding | None:
    """
    Get a cached embedding model by key.
    
    Args:
        cache_key (str): Cache key (e.g., "project_id:DOCS" or "project_id:CODE")
        
    Returns:
        BaseEmbedding | None: Cached embedding model or None if not found
    """
    model = _embedding_cache.get(cache_key)
    if model:
        logger.debug(f"Embedding cache HIT for key: {cache_key}")
    else:
        logger.debug(f"Embedding cache MISS for key: {cache_key}")
    return model


async def cache_embedding(cache_key: str, embedding_model: BaseEmbedding) -> None:
    """
    Cache an embedding model.

    TODO: Consider having fixed number of embeddings cached at any given time to reduce memory usage
    
    Args:
        cache_key (str): Cache key (e.g., "project_id:DOCS" or "project_id:CODE")
        embedding_model (BaseEmbedding): The embedding model to cache
    """
    async with _cache_lock:
        _embedding_cache[cache_key] = embedding_model
        logger.info(f"Cached embedding model for key: {cache_key}. Total cached: {len(_embedding_cache)}")


def invalidate_cache_key(cache_key: str) -> None:
    """
    Remove a cached embedding model.
    
    Args:
        cache_key (str): Cache key to invalidate
    """
    if cache_key in _embedding_cache:
        del _embedding_cache[cache_key]
        logger.info(f"Invalidated embedding cache for key: {cache_key}")


def invalidate_project_cache(project_id: UUID) -> None:
    """
    Remove all cached embeddings for a project.
    
    Args:
        project_id (UUID): Project ID to invalidate
    """
    prefix = str(project_id)
    keys_to_remove = [key for key in _embedding_cache.keys() if key.startswith(prefix)]
    for key in keys_to_remove:
        del _embedding_cache[key]
        logger.info(f"Invalidated embedding cache for key: {key}")


def clear_all_cache() -> None:
    """Clear all cached embeddings."""
    _embedding_cache.clear()
    logger.info("Cleared all embedding cache")


def get_cache_stats() -> dict[str, int | list[str]]:
    """Get statistics about the cache."""
    return {
        "total_cached_models": len(_embedding_cache),
        "cached_keys": list(_embedding_cache.keys())
    }

