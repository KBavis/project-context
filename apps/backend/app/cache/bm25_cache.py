from __future__ import annotations

import logging
from collections import OrderedDict

from llama_index.core.retrievers import BaseRetriever

from app.core import settings

logger = logging.getLogger(__name__)


# Key = (data source ID the index was built over, k baked into the retriever).
BM25CacheKey = tuple[str, int]


class BM25RetrieverCache:
    """
    Process-wide LRU cache of prebuilt BM25 retrievers.

    Building one loads every docstore node and tokenizes a term index, so we cache
    the built object and reuse it until the underlying corpus changes (see invalidate).
    Each entry can hold hundreds of MB, so the cache is bounded by capacity and evicts
    the least-recently-used entry — preventing unbounded growth when many distinct
    (data-source, k) combinations are searched.
    """

    _cache: OrderedDict[BM25CacheKey, BaseRetriever] = OrderedDict()

    @classmethod
    def build_key(cls, data_source_id: str, k: int) -> BM25CacheKey:
        return (data_source_id, k)

    @classmethod
    def get(cls, key: BM25CacheKey) -> BaseRetriever | None:
        retriever = cls._cache.get(key)
        if retriever is not None:
            cls._cache.move_to_end(key)  # mark most-recently-used
        return retriever

    @classmethod
    def put(cls, key: BM25CacheKey, retriever: BaseRetriever) -> None:
        cls._cache[key] = retriever
        cls._cache.move_to_end(key)  # mark most-recently-used

        # evict least-recently-used entries once over capacity
        while len(cls._cache) > settings.BM25_RETRIEVER_CACHE_CAPACITY:
            evicted_key, _ = cls._cache.popitem(last=False)
            logger.debug(f"Evicted LRU BM25 retriever for key={evicted_key}")

    @classmethod
    def invalidate(cls, data_source_id) -> None:
        """
        Drop every cached retriever whose corpus includes this data source, so the next
        search rebuilds against the updated docstore. Called when ingestion writes nodes.
        """
        target = str(data_source_id)
        stale = [key for key in cls._cache if key[0] == target]
        for key in stale:
            del cls._cache[key]
        if stale:
            logger.info(f"Invalidated {len(stale)} cached BM25 retriever(s) for DataSource={target}")
