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

from sqlalchemy import select, or_
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


    async def grep_search(
        self, 
        key_word: str,
        data_source_ids: list[str],
        data_source_file_ids: dict[str, list[str]] | None = None,
        scoped_repo_data_source_ids: list[str] | None = None,
        k: int = 10
    ):
        """
        Functionality to retrieve ingested Documentation / Code chunks based on _exeact_ variable names, function
        defintiions, or error codes. This functionality WILL NOT be leveraging any semantic meaning, it will only be 
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
                ds_str = str(ds_id)
                ds_namespace = f"{ds_str}/data"
                
                # Apply file_id filters ONLY if this data source is issue-scoped
                if scoped_repo_data_source_ids and ds_str in scoped_repo_data_source_ids:
                    touched_ids = data_source_file_ids.get(ds_str, []) if data_source_file_ids else []
                    if touched_ids:
                        ds_filters.append(
                            and_(
                                DocstoreChunk.namespace == ds_namespace,
                                or_(
                                    DocstoreChunk.value['__data__']['metadata']['file_id'].astext.in_(touched_ids),
                                    DocstoreChunk.value['metadata']['file_id'].astext.in_(touched_ids)
                                )
                            )
                        )
                    # If it is scoped but has no touched files, we do NOT add it to ds_filters.
                    # This means no chunks from this DS will be returned.
                else:
                    # Unscoped DS: no file_id filtering needed, just allow the namespace
                    ds_filters.append(DocstoreChunk.namespace == ds_namespace)

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
        data_source_file_ids: dict[str, list[str]] | None = None,
        scoped_repo_data_source_ids: list[str] | None = None,
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
        chunks = await self._get_chunks(query, collections, embedding, llm, k, data_source_ids, data_source_file_ids, scoped_repo_data_source_ids)
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
        data_source_file_ids: dict[str, list[str]] | None = None,
        scoped_repo_data_source_ids: list[str] | None = None
    ) -> list["NodeWithScore"]:
        """
        Retrieve chunks directly from ChromaDB based on the query and specified collections
        """
        try:
            # configure the retrievers
            retrievers = []
            for collection in collections:
                chroma_retriever = await self._get_chroma_retreiver(collection, embedding, k, data_source_file_ids, scoped_repo_data_source_ids)
                retrievers.append(chroma_retriever)
            
            # configure BM25 retriever
            bm25_retriever = await self._get_bm25_retriever(k, data_source_ids, data_source_file_ids, scoped_repo_data_source_ids)
            retrievers.append(bm25_retriever)

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
        k: int,
        data_source_ids: list[str],
        data_source_file_ids: dict[str, list[str]] | None = None,
        scoped_repo_data_source_ids: list[str] | None = None
    ) -> BaseRetriever:
        """
        Configure BM25 Retriever for Hybrid Search functionality based on all 
        nodes assocaited with Data Sources in Postgres KV Store 

        Args:
            k (int): the number of chunks to retrieve
            data_source_ids (list): list of data source's to filter search by 
        """

        # To support scoped retrieval, if we have a scoped data source, we must rebuild the cache key
        # by hashing the actual allowed file IDs or just building it dynamically. Since BM25 cache is
        # meant for all files, if we have scoped files, we just bypass the cache and build it for the touched files.
        is_scoped = False
        if scoped_repo_data_source_ids:
            for ds_id in data_source_ids:
                if str(ds_id) in scoped_repo_data_source_ids:
                    is_scoped = True
                    break

        if not is_scoped:
            # serve from cache when the same data sources were already indexed at this k
            cache_key = BM25RetrieverCache.build_key(data_source_ids, k)
            cached = BM25RetrieverCache.get(cache_key)
            if cached is not None:
                logger.info(f"Reusing cached BM25 retriever for Data Sources={data_source_ids}, k={k}")
                return cached

        return self._build_and_cache_bm25(k, data_source_ids, data_source_file_ids if is_scoped else None, scoped_repo_data_source_ids, should_cache=not is_scoped)


    def _build_and_cache_bm25(
        self,
        k: int,
        data_source_ids: list[str],
        data_source_file_ids: dict[str, list[str]] | None = None,
        scoped_repo_data_source_ids: list[str] | None = None,
        should_cache: bool = True
    ) -> BaseRetriever:
        """
        Synchronously load every docstore node and build + cache the BM25 retriever.

        This body is intentionally synchronous and blocking (Postgres node loading +
        in-memory tokenization). Callers on the event loop should offload it to a
        worker thread (see warm_bm25_cache) so the build doesn't stall the loop.
        """
        cache_key = BM25RetrieverCache.build_key(data_source_ids, k)

        # configure Postgres KV Store
        from app.core.relational_db import sync_engine, async_engine
        kv_store = PostgresKVStore(
            table_name=settings.CHUNKS_DOC_STORE,
            engine=sync_engine,
            async_engine=async_engine,
            use_jsonb=True, 
            perform_setup=True
        )

        # retrieve all nodes associated with filtered Data Source IDs
        all_nodes = []
        logger.info(f"Building BM25 Retreiver based on Data Source IDs: {data_source_ids}")

        for id in data_source_ids:
            doc_store = PostgresDocumentStore(
                kv_store, 
                namespace=str(id)
            )

            ds_nodes = list(doc_store.docs.values())
            
            # Apply scope filter for this DataSource if it is issue-scoped
            if scoped_repo_data_source_ids and str(id) in scoped_repo_data_source_ids:
                allowed_files = set(data_source_file_ids.get(str(id), [])) if data_source_file_ids else set()
                ds_nodes = [n for n in ds_nodes if n.metadata.get('file_id') in allowed_files]

            all_nodes.extend(ds_nodes)
        
        # configure BM25 retreiver based on all nodes, then cache it for reuse
        retriever = BM25Retriever.from_defaults(
            nodes=all_nodes,
            similarity_top_k=k
        )
        if should_cache:
            BM25RetrieverCache.put(cache_key, retriever)
            logger.info(f"Cached BM25 retriever ({len(all_nodes)} nodes) for Data Sources={data_source_ids}, k={k}")
        else:
            logger.info(f"Built un-cached scoped BM25 retriever ({len(all_nodes)} nodes) for Data Sources={data_source_ids}, k={k}")
            
        return retriever


    async def warm_bm25_cache(
        self,
        data_source_ids: list[str],
        k: int = DEFAULT_SEARCH_K
    ) -> None:
        """
        Pre-build and cache the BM25 retriever so the first semantic_search of a
        conversation doesn't pay the full index-build cost inline.

        Intended to be fired off as a background task at the start of an agent run.
        The build is offloaded to a worker thread so it overlaps (rather than blocks)
        the rest of the run, and any failure is logged and swallowed — a warmup miss
        must never break the conversation (the inline search path will simply rebuild).

        Args:
            data_source_ids (list[str]): data sources to index — must match the set the
                first search resolves to, since the cache key is (data_source_ids, k).
            k (int): chunk count baked into the retriever; defaults to DEFAULT_SEARCH_K
                to match semantic_search's default so the warmed key is reused.
        """
        if not data_source_ids:
            return

        # already warm — nothing to do
        if BM25RetrieverCache.get(BM25RetrieverCache.build_key(data_source_ids, k)) is not None:
            return

        try:
            logger.info(f"Warming BM25 cache in background for Data Sources={data_source_ids}, k={k}")
            await asyncio.to_thread(self._build_and_cache_bm25, k, data_source_ids)
        except Exception as e:
            logger.warning(f"Background BM25 cache warmup failed for Data Sources={data_source_ids}, k={k}: {e}")
        

    async def _get_chroma_retreiver(self, collection: ChromaCollection, embedding: BaseEmbedding, k: int, data_source_file_ids: dict[str, list[str]] | None = None, scoped_repo_data_source_ids: list[str] | None = None) -> BaseRetriever:
        """
        Get retriever associated with relevant Chroma Collection 

        Args:
            collection (ChromaCollection): the Chroma collection to retrieve retriever from
            embedding (BaseEmbedding): the LlamaIndex embedding model to use for querying
            k (int): the number of chunks to retrieve
        """

        # get actual Chroma Collection 
        chroma_collection = self.chroma_svc.get_real_chroma_collection(collection_name=collection.name)

        # configure LlamaIndex retriever from Chroma collection 
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, embed_model=embedding) # pass embed_model explicitly to avoid race conditions with global Settings
        
        filters = None
        ds_id_str = str(collection.data_source_id)
        if scoped_repo_data_source_ids and ds_id_str in scoped_repo_data_source_ids:
            touched_ids = data_source_file_ids.get(ds_id_str, []) if data_source_file_ids else []
            if touched_ids:
                filters = MetadataFilters(
                    filters=[
                        MetadataFilter(
                            key="file_id", 
                            value=touched_ids, 
                            operator=FilterOperator.IN
                        )
                    ]
                )
            else:
                # If the DS is scoped but has NO touched files, we query with a filter that returns nothing
                filters = MetadataFilters(
                    filters=[
                        MetadataFilter(
                            key="file_id", 
                            value=["impossible-value-no-files-touched"], 
                            operator=FilterOperator.IN
                        )
                    ]
                )

        return index.as_retriever(similarity_top_k=k, filters=filters)
        


