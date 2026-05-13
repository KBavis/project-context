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
from app.services.data_source import DataSourceService
from app.core import settings
from app.models.collection import ChromaCollection
from app.embeddings import EmbeddingManager
from app.models.docstore_chunk import DocstoreChunk

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import logging
from typing import Optional
from uuid import UUID


logger = logging.getLogger(__name__)

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
        project_id: UUID,
        k: int = 10,
        data_source_ids: Optional[list[UUID]] = None
    ):
        """
        Functionality to retrieve ingested Documentation / Code chunks based on _exeact_ variable names, function
        defintiions, or error codes. This functionality WILL NOT be leveraging any semantic meaning, it will only be 
        searching for raw chunks that could help provide context to the Agent 

        Args:
            key_word (str): the exact text string to search for
            project_id (UUID): the project the search corresponds to
            k (int): the number of chunks to retrieve --> default is 10 chunks
            data_source_ids (Optional[list[str]]): optional list of data source IDs to limit the search to
        """
        # 1. Resolve Data Source IDs (if none provided, search the whole project)
        if not data_source_ids:
            data_source_ids = await self._get_data_source_ids_by_project(project_id)
            
        logger.info(f"Performing grep search for '{key_word}' in Data Sources: {data_source_ids}")

        # 2. Build and execute the SQLAlchemy query 
        stmt = (
            select(DocstoreChunk)
            .where(DocstoreChunk.namespace.in_([str(id) for id in data_source_ids]))
            .where(
                DocstoreChunk.value['__data__']['text'].astext.op('~*')(key_word)
            )
            .limit(k)
        )
        result = await self.db.execute(stmt)
        docstore_chunks = result.scalars().all()

        # 3. Format the chunks for the LLM
        formatted_chunks = []
        for chunk in docstore_chunks:
            data_source = chunk.node_metadata.get('data_source_id', 'Unknown Data Source ID')
            file_path = chunk.node_metadata.get('file_path', 'Unknown File Path')
            text_content = chunk.node_text
            
            formatted_chunks.append(f"Data Source:{data_source}\nFile Path:{file_path}\nContent:\n{text_content}")
            
        return formatted_chunks

        
    async def semantic_search(
        self, 
        query: str,
        project_id: UUID,
        llm: LLMBase,
        k: int = 10,
        data_source_ids: Optional[list[str]] = None
    ):
        """
        Functionality to retrieve ingested Documentation / Code based on a) semantic reasoning (from vector's stored
        in ChromaDB), b) key word search (BM25)

        Args:
            query (str): query to retrieve chunks for 
            project_id (UUID): the project to retrieve chunks for 
            llm (LLMBase): the LLM associated with the Conversation 
            k (int): the number of chunks to retrieve --> default is 10 chunks
            data_source_ids (Optional[list[str]]): optional list of data source IDs to limit the search to
        """


        # retreive relevant Chroma Collections corresponding to Project 
        collection = self.chroma_svc.get_collection_by_project(project_id)
        if not collection:
            raise Exception(f"No ingested data found for Project ID: {project_id}")
        
        # retreive cached embedding model
        embedding_manager = EmbeddingManager(collection, project_id=project_id)
        embedding = await embedding_manager.aget_embedding_model_cached()
        
        # retrieve chunks based on query        
        chunks = await self._get_chunks(query, collection, embedding, llm, k, data_source_ids)

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
        collection: ChromaCollection, 
        embedding: BaseEmbedding,
        llm: LLMBase,
        k: int,
        data_source_ids: Optional[list[str]] = None
    ) -> list["NodeWithScore"]:
        """
        Retrieve chunks directly from ChromaDB based on the query and specified collection

        Args:
            query (str): user passed in query
            collection (ChromaCollection): the Chroma collection to query against
            embedding: the LlamaIndex embedding model to use for querying
            llm (LLMBase): the LLM associated with the Conversation
            k (int): the number of chunks to retrieve --> default is 10 chunks
            data_source_ids (Optional[list[str]]): optional list of data source IDs to limit the search to
        """
        
        # configure the retrievers
        chroma_retriever = await self._get_chroma_retreiver(collection, embedding, k, data_source_ids)
        bm25_retriever = await self._get_bm25_retriever(collection, k, data_source_ids)

        # configure the fusion retriever (hybrid cordinator for both seamtnic and direct comparisons)
        fusion_retriever = QueryFusionRetriever(
            [chroma_retriever, bm25_retriever], 
            similarity_top_k=k,
            num_queries=1,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            use_async=True,
            llm=llm
        )

        nodes = await fusion_retriever.aretrieve(query)

        return nodes 


    async def _get_bm25_retriever(
        self, 
        collection: ChromaCollection, 
        k: int,
        data_source_id_filter: Optional[list[str]] = None
    ) -> BaseRetriever:
        """
        Configure BM25 Retriever for Hybrid Search functionality based on all 
        nodes assocaited with Project in Postgres KV Store 

        Args:
            collection (ChromaCollection): the Chroma collection to retrieve retriever from
            k (int): the number of chunks to retrieve
            data_source_ids (list): optional list of data source's to filter search by (if not provided, all will be used)
        """

        # configure Postgres KV Store
        from app.core.relational_db import sync_engine, async_engine
        kv_store = PostgresKVStore(
            table_name=settings.CHUNKS_DOC_STORE,
            engine=sync_engine,
            async_engine=async_engine,
            use_jsonb=True, 
            perform_setup=True
        )

        # retrieve all nodes associated with Project or filtered Data Source IDs
        all_nodes = []
        data_source_ids = await self._get_data_source_ids_by_project(collection.project_id) if not data_source_id_filter else data_source_id_filter
        logger.info(f"Filtering BM25 Retreiver based on Data Source IDs: {data_source_ids}")

        for id in data_source_ids:
            doc_store = PostgresDocumentStore(
                kv_store, 
                namespace=str(id)
            )

            all_nodes.extend(doc_store.docs.values())
        
        # configure BM25 retreiver based on all nodes 
        return BM25Retriever.from_defaults(
            nodes=all_nodes,
            similarity_top_k=k
        )
        

    async def _get_chroma_retreiver(self, collection: ChromaCollection, embedding: BaseEmbedding, k: int, data_source_ids: Optional[list[str]] = None) -> BaseRetriever:
        """
        Get retriever associated with relevant Chroma Collection 

        Args:
            collection (ChromaCollection): the Chroma collection to retrieve retriever from
            embedding (BaseEmbedding): the LlamaIndex embedding model to use for querying
            k (int): the number of chunks to retrieve
            data_source_ids (Optional[list[str]]): optional list of data source's to filter search by (if not provided, all will be used)
        """

        # get actual Chroma Collection 
        chroma_collection = self.chroma_svc.get_real_chroma_collection(collection_name=collection.name)

        # configure filter (if needed)
        filters = None 
        if data_source_ids:
            logger.info(f"Filtering ChromaRetriever based on selected Data Source IDs: {data_source_ids}")

            filters = MetadataFilters(
                filters=[
                    MetadataFilter(
                        key="data_source_id",
                        value=data_source_ids,
                        operator=FilterOperator.IN
                    )
                ]
            )

        # configure LlamaIndex retriever from Chroma collection 
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, embed_model=embedding) # pass embed_model explicitly to avoid race conditions with global Settings
        
        return index.as_retriever(similarity_top_k=k, filters=filters) if filters else index.as_retriever(similarity_top_k=k)
        

    async def _get_data_source_ids_by_project(self, project_id: UUID) -> list[UUID]:
        """
        Get all data source IDs for a given project.

        Args:
            project_id (UUID): The project ID.
        """

        data_sources = await self.data_source_svc.aget_project_data_sources(project_id)
        data_source_ids = [data_source.id for data_source in data_sources]
        return data_source_ids
