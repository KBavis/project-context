from __future__ import annotations

from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import BaseRetriever, QueryFusionRetriever
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.storage.docstore.postgres import PostgresDocumentStore
from llama_index.storage.kvstore.postgres import PostgresKVStore
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator

from app.llm import LLMBase
from app.services.chroma import ChromaService
from app.cache import BM25RetrieverCache
from app.services.data_source import DataSourceService
from app.core import settings
from app.models.collection import ChromaCollection
from app.embeddings import EmbeddingManager
from app.models.docstore_chunk import DocstoreChunk

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

import asyncio
import logging
from typing import Optional
from uuid import UUID


logger = logging.getLogger(__name__)

# default chunk count for semantic search
DEFAULT_SEARCH_K = 10

class ChunkRetrievalService:
    """
    Service dedicated to the retrieval of chunks from Chroma based on a 
    users query
    """

    def __init__(self, db: AsyncSession, chroma_svc: ChromaService, data_source_svc: DataSourceService):
        self.db: AsyncSession = db
        self.chroma_svc: ChromaService = chroma_svc
        self.data_source_svc: DataSourceService = data_source_svc


    @staticmethod
    def _resolve_file_scope(
        ds_id: str, scope_map: dict[str, list[str]] | None
    ) -> list[str] | None:
        if not scope_map or ds_id not in scope_map:
            return None        # unrestricted
        return scope_map[ds_id]  # [] = nothing, non-empty = restrict


    async def grep_search(
        self, 
        key_word: str,
        data_source_ids: list[str],
        scope_map: dict[str, list[str]] | None = None,
        k: int = 10
    ):
        """
        Functionality to retrieve ingested Documentation / Code chunks based on _exact_ variable names, function
        definitions, or error codes. This functionality WILL NOT be leveraging any semantic meaning, it will only be 
        searching for raw chunks that could help provide context to the Agent 

        Args:
            key_word (str): the exact text string to search for
            data_source_ids (list[str]): list of data source IDs to limit the search to
            k (int): the number of chunks to retrieve --> default is 10 chunks
        """

        try:
            if not data_source_ids:
                logger.warning("No Data Sources provided for grep search")
                return []
                
            logger.info(f"Performing grep search for '{key_word}' in Data Sources: {data_source_ids}")

            # 2. Build and execute the SQLAlchemy query 
            ds_filters = []
            for ds_id in data_source_ids:
                ds_namespace = f"{ds_id}/data"
                
                scope = self._resolve_file_scope(ds_id, scope_map)
                if scope is None:
                    # Unscoped DS: no file_id filtering needed, just allow the namespace
                    ds_filters.append(DocstoreChunk.namespace == ds_namespace)
                elif len(scope) > 0:
                    # Scoped DS with files
                    ds_filters.append(
                        and_(
                            DocstoreChunk.namespace == ds_namespace,
                            or_(
                                DocstoreChunk.value['__data__']['metadata']['file_id'].astext.in_(scope),
                                DocstoreChunk.value['metadata']['file_id'].astext.in_(scope)
                            )
                        )
                    )
                # If scope is [] (scoped but nothing touched), we skip the DS (do nothing)

            if not ds_filters:
                # All requested data sources were scoped but had no touched files.
                return []

            stmt = (
                select(DocstoreChunk)
                .where(or_(*ds_filters))
                .where(
                    or_(
                        DocstoreChunk.value['__data__']['text'].astext.op('~*')(key_word),
                        DocstoreChunk.value['text'].astext.op('~*')(key_word)
                    )
                )
                .limit(k)
            )
            
            result = await self.db.execute(stmt)
            docstore_chunks = result.scalars().all()
            if not docstore_chunks:
                logger.warning(f"No chunks retrieved for Keyword={key_word}, Data Sources={data_source_ids}")

            # 3. Format the chunks for the LLM
            formatted_chunks = []
            for chunk in docstore_chunks:
                data_source = chunk.node_metadata.get('data_source_id', 'Unknown Data Source ID')
                file_path = chunk.node_metadata.get('file_path', 'Unknown File Path')
                text_content = chunk.node_text
                
                formatted_chunks.append(f"Data Source:{data_source}\nFile Path:{file_path}\nContent:\n{text_content}")
                
            return formatted_chunks
        except Exception as e:
            logger.error(f"Error performing grep search for keyword={key_word}, data_source_ids={data_source_ids}", e)
            return []

    async def retrieve_sequential_chunks(self, file_path: str, data_source_id: UUID) -> str:
        """
        Retrieve all chunks for a given file_path, ordered by their sequence index in the DocStore.
        This allows viewing the text content of documents (like PDFs) without downloading the raw binary.
        """
        try:
            db_namespace = f"{str(data_source_id)}/data"
            logger.info(f"Retrieving sequential chunks for file='{file_path}' in DocStore namespace='{db_namespace}'")
            
            stmt = (
                select(DocstoreChunk)
                .where(DocstoreChunk.namespace == db_namespace)
                .where(
                    or_(
                        DocstoreChunk.value['__data__']['metadata']['file_path'].astext == file_path,
                        DocstoreChunk.value['metadata']['file_path'].astext == file_path
                    )
                )
            )
            result = await self.db.execute(stmt)
            chunks = result.scalars().all()
            
            if not chunks:
                logger.warning(f"No chunks found in DocStore for file path '{file_path}' under namespace '{db_namespace}'")
                return f"No chunks found in DocStore for file path: {file_path}"

            # Sort chunks by their original index (suffix of the key/id_ e.g., 'file_id_hash_idx')
            def get_chunk_idx(c: DocstoreChunk) -> int:
                try:
                    parts = c.key.split('_')
                    return int(parts[-1])
                except Exception:
                    return 0

            sorted_chunks = sorted(chunks, key=get_chunk_idx)
            logger.info(f"Retrieved and sorted {len(sorted_chunks)} chunks for file '{file_path}'")
            
            # Combine the chunk text contents
            reconstructed_text = []
            for chunk in sorted_chunks:
                text = chunk.node_text
                if text:
                    reconstructed_text.append(text)
            
            return "\n\n--- Chunk Divider ---\n\n".join(reconstructed_text)
            
        except Exception as e:
            logger.error(f"Error retrieving sequential chunks for file={file_path}", exc_info=True)
            return f"Error retrieving sequential chunks from DocStore: {str(e)}"

    async def semantic_search(
        self, 
        query: str,
        llm: LLMBase,
        data_source_ids: list[str],
        scope_map: dict[str, list[str]] | None = None,
        k: int = DEFAULT_SEARCH_K
    ):
        """
        Functionality to retrieve ingested Documentation / Code based on a) semantic reasoning (from vector's stored
        in ChromaDB), b) key word search (BM25)

        Args:
            query (str): query to retrieve chunks for 
            llm (LLMBase): the LLM associated with the Conversation 
            data_source_ids (list[str]): list of data source IDs to search in
            k (int): the number of chunks to retrieve --> default is 10 chunks
        """
        logger.info(f"Performing semantic search for Query={query}, Data Sources={data_source_ids}")

        if not data_source_ids:
            logger.warning("No Data Sources provided for semantic search")
            return []

        # retreive relevant Chroma Collections corresponding to Data Sources 
        collections = []
        for ds_id in data_source_ids:
            try:
                col = await self.chroma_svc.aget_collection_by_data_source(UUID(ds_id))
                if col:
                    collections.append(col)
            except Exception as e:
                logger.warning(f"Could not fetch collection for Data Source ID {ds_id}: {e}")

        if not collections:
            logger.warning(f"No ingested data found for Data Source IDs: {data_source_ids}")
            return []
        
        # retreive cached embedding model
        embedding = await EmbeddingManager.aget_embedding_model_cached()
        
        # retrieve chunks based on query        
        chunks = await self._get_chunks(query, collections, embedding, llm, k, data_source_ids, scope_map)
        if not chunks:
            logger.warning(f"No chunks retrieved for Query={query}, Data Sources={data_source_ids}")

        # format chunks (data source ID: chunk content) 
        formatted_chunks = []
        for chunk in chunks:
            data_source = chunk.node.metadata.get('data_source_id', "Unknown Data Source ID")
            file_path = chunk.node.metadata.get('file_path', "Unknown File Path")
            text_content = chunk.node.get_content()
            formatted_chunks.append(f"Data Source:{data_source}\nFile Path:{file_path}\nContent:\n{text_content}")

        return formatted_chunks


    async def _get_chunks(
        self, 
        query: str, 
        collections: list[ChromaCollection], 
        embedding: BaseEmbedding,
        llm: LLMBase,
        k: int,
        data_source_ids: list[str],
        scope_map: dict[str, list[str]] | None = None
    ) -> list["NodeWithScore"]:
        """
        Retrieve chunks directly from ChromaDB based on the query and specified collections
        """
        try:
            # configure the retrievers
            retrievers = []
            for collection in collections:
                ds_id_str = str(collection.data_source_id)
                scope = self._resolve_file_scope(ds_id_str, scope_map)
                if scope == []:
                    # Skip building the retriever for this collection (empty scope)
                    continue
                chroma_retriever = await self._get_chroma_retreiver(collection, embedding, k, scope)
                retrievers.append(chroma_retriever)
            
            # configure BM25 retriever per DS
            for ds_id in data_source_ids:
                scope = self._resolve_file_scope(ds_id, scope_map)
                if scope == []:
                    # Skip the data source entirely (empty scope)
                    continue
                bm25_retriever = await self._get_bm25_retriever(ds_id, k, scope)
                retrievers.append(bm25_retriever)

            if not retrievers:
                return []

            # configure the fusion retriever (hybrid cordinator for both seamtnic and direct comparisons)
            fusion_retriever = QueryFusionRetriever(
                retrievers, 
                similarity_top_k=k,
                num_queries=1,
                mode=FUSION_MODES.RECIPROCAL_RANK,
                use_async=True,
                llm=llm.get_llama_idx_instance()
            )

            nodes = await fusion_retriever.aretrieve(query)
            return nodes 
        
        except Exception as e:
            logger.error(f"Exception occurred while attempting to recieve Chunks for Query={query}, Data Sources={data_source_ids}, and LLM={llm.provider}/{llm.model_name}", e)
            return []
            



    async def _get_bm25_retriever(
        self, 
        data_source_id: str,
        k: int,
        scope: list[str] | None = None
    ) -> BaseRetriever:
        """
        Configure BM25 Retriever for Hybrid Search functionality based on a single
        Data Source in Postgres KV Store.
        """
        if scope is None:
            # serve from cache when the same data source was already indexed at this k
            cache_key = BM25RetrieverCache.build_key(data_source_id, k)
            cached = BM25RetrieverCache.get(cache_key)
            if cached is not None:
                logger.info(f"Reusing cached BM25 retriever for Data Source={data_source_id}, k={k}")
                return cached
            return self._build_and_cache_bm25(data_source_id, k, scope=None, should_cache=True)
            
        return self._build_and_cache_bm25(data_source_id, k, scope=scope, should_cache=False)


    def _build_and_cache_bm25(
        self,
        data_source_id: str,
        k: int,
        scope: list[str] | None = None,
        should_cache: bool = True
    ) -> BaseRetriever:
        """
        Synchronously load docstore nodes for a single data source and build (+ cache if unscoped) the BM25 retriever.
        """
        cache_key = BM25RetrieverCache.build_key(data_source_id, k)

        # configure Postgres KV Store
        from app.core.relational_db import sync_engine, async_engine
        kv_store = PostgresKVStore(
            table_name=settings.CHUNKS_DOC_STORE,
            engine=sync_engine,
            async_engine=async_engine,
            use_jsonb=True, 
            perform_setup=True
        )

        logger.info(f"Building BM25 Retriever for Data Source ID: {data_source_id}")

        doc_store = PostgresDocumentStore(
            kv_store, 
            namespace=data_source_id
        )

        ds_nodes = list(doc_store.docs.values())
        
        # Apply scope filter if present (scope is non-empty list of file IDs)
        if scope:
            allowed_files = set(scope)
            ds_nodes = [n for n in ds_nodes if n.metadata.get('file_id') in allowed_files]

        # configure BM25 retriever based on nodes, then cache if allowed
        retriever = BM25Retriever.from_defaults(
            nodes=ds_nodes,
            similarity_top_k=k
        )
        if should_cache:
            BM25RetrieverCache.put(cache_key, retriever)
            logger.info(f"Cached BM25 retriever ({len(ds_nodes)} nodes) for Data Source={data_source_id}, k={k}")
        else:
            logger.info(f"Built un-cached scoped BM25 retriever ({len(ds_nodes)} nodes) for Data Source={data_source_id}, k={k}")
            
        return retriever


    async def warm_bm25_cache(
        self,
        data_source_ids: list[str],
        k: int = DEFAULT_SEARCH_K
    ) -> None:
        """
        Pre-build and cache the BM25 retriever so the first semantic_search of a
        conversation doesn't pay the full index-build cost inline.
        """
        if not data_source_ids:
            return

        for ds_id in data_source_ids:
            cache_key = BM25RetrieverCache.build_key(ds_id, k)
            if BM25RetrieverCache.get(cache_key) is not None:
                continue

            try:
                logger.info(f"Warming BM25 cache in background for Data Source={ds_id}, k={k}")
                await asyncio.to_thread(self._build_and_cache_bm25, ds_id, k, None, True)
            except Exception as e:
                logger.warning(f"Background BM25 cache warmup failed for Data Source={ds_id}, k={k}: {e}")


    async def _get_chroma_retreiver(
        self,
        collection: ChromaCollection,
        embedding: BaseEmbedding,
        k: int,
        scope: list[str] | None = None
    ) -> BaseRetriever:
        """
        Get retriever associated with relevant Chroma Collection 
        """
        # get actual Chroma Collection 
        chroma_collection = self.chroma_svc.get_real_chroma_collection(collection_name=collection.name)

        # configure LlamaIndex retriever from Chroma collection 
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, embed_model=embedding)
        
        filters = None
        if scope is not None:
            # scope is a non-empty list of file IDs
            filters = MetadataFilters(
                filters=[
                    MetadataFilter(
                        key="file_id", 
                        value=scope, 
                        operator=FilterOperator.IN
                    )
                ]
            )

        return index.as_retriever(similarity_top_k=k, filters=filters)
        


