import asyncio
from llama_index.core.embeddings import BaseEmbedding
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

class EmbeddingCacheNode():
    def __init__(self, key: str, value: BaseEmbedding | None):
        self.key = key 
        self.value = value 
        self.prev: EmbeddingCacheNode | None = None 
        self.next: EmbeddingCacheNode | None = None 


_embedding_cache: dict[str, EmbeddingCacheNode] = {} 
_cache_lock = asyncio.Lock()

_capacity = settings.EMBEDDING_CACHE_CAPACITY
_lru: EmbeddingCacheNode = EmbeddingCacheNode("", None)
_mru: EmbeddingCacheNode = EmbeddingCacheNode("", None)
_lru.next = _mru 
_mru.prev = _lru
    

    
def add_embedding_node(node: EmbeddingCacheNode):
    """
    Insert a new embedding node into Doubly Linked List 

    Args:
        node (EmbeddingCacheNode): The embedding node to add
    """ 

    prev_node= _mru.prev 

    _mru.prev = node 
    if prev_node:
        prev_node.next = node 
    node.prev = prev_node
    node.next = _mru

def remove_embedding_node(node: EmbeddingCacheNode):
    """
    Remove an embedding node from Doubly Linked List 

    Args:
        node (EmbeddingCacheNode): The embedding node to remove
    """

    prev_node = node.prev 
    next_node = node.next 

    if prev_node:
        prev_node.next = next_node 
    if next_node:
        next_node.prev = prev_node 


async def get_cached_embedding(key: str) -> BaseEmbedding | None:
    async with _cache_lock:
        if key in _embedding_cache:
            logger.debug(f"Embedding cache HIT for key: {key}")

            node = _embedding_cache[key]
            remove_embedding_node(node)
            add_embedding_node(node)

            return node.value
        
        logger.debug(f"Embedding cache MISS for key: {key}")
        return None 


async def cache_embedding(key: str, value: BaseEmbedding):

    async with _cache_lock:

        # account for existing key updates 
        if key in _embedding_cache:
            logger.debug(f"Existing embedding HIT for key: {key}, updating node with new value")
            node = _embedding_cache[key]
            remove_embedding_node(node)
            del _embedding_cache[key]
        
        # remove LRU node if cache is full 
        if len(_embedding_cache) == _capacity:
            lru_node = _lru.next 
            if lru_node and lru_node != _mru:
                remove_embedding_node(lru_node)
                del _embedding_cache[lru_node.key]
                logger.debug(f"Evicted LRU embedding for key: {lru_node.key}")
        

        # insert new node 
        new_node = EmbeddingCacheNode(key, value)
        add_embedding_node(new_node)
        _embedding_cache[key] = new_node


        logger.info(f"Added embedding for key: {key}. Total cached: {len(_embedding_cache)}")


async def invalidate_cache_key(cache_key: str) -> None:
    """
    Remove a cached embedding model.
    
    Args:
        cache_key (str): Cache key to invalidate
    """
    async with _cache_lock:
        if cache_key in _embedding_cache:
            node = _embedding_cache[cache_key]
            remove_embedding_node(node)
            del _embedding_cache[cache_key]
            logger.info(f"Invalidated embedding cache for key: {cache_key}")


async def invalidate_project_cache(project_id: str) -> None:
    """
    Remove all cached embeddings for a project.
    
    Args:
        project_id (str): Project ID to invalidate (will be converted to string)
    """
    async with _cache_lock:
        prefix = str(project_id)
        keys_to_remove = [key for key in _embedding_cache.keys() if key.startswith(prefix)]
        for key in keys_to_remove:
            node = _embedding_cache[key]
            remove_embedding_node(node)
            del _embedding_cache[key]
            logger.info(f"Invalidated embedding cache for key: {key}")


async def clear_all_cache() -> None:
    """Clear all cached embeddings."""
    async with _cache_lock:
        _embedding_cache.clear()
        # Reset the doubly linked list
        _lru.next = _mru
        _mru.prev = _lru
        logger.info("Cleared all embedding cache")


def get_cache_stats() -> dict[str, int | list[str]]:
    """Get statistics about the cache."""
    return {
        "total_cached_models": len(_embedding_cache),
        "cached_keys": list(_embedding_cache.keys()),
        "capacity": _capacity
    }


