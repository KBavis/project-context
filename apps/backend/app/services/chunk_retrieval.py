from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import CrossEncoder

from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import BaseRetriever, QueryFusionRetriever
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.storage.docstore.postgres import PostgresDocumentStore
from llama_index.storage.kvstore.postgres import PostgresKVStore

from app.services.chroma import ChromaService
from app.services.data_source import DataSourceService
from app.core import DOCS, CODE, settings
from app.models.collection import ChromaCollection

from app.embeddings import EmbeddingManager

import logging
from typing import Any
from uuid import UUID
import asyncio

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



    async def retrieve_chunks_by_decomposition(
        self, 
        decomposition: dict[str, Any], 
        project_id: UUID,
        original_query: str,
        llm: Any | None = None
    ) -> list["NodeWithScore"]:
        """
        Retrieve chunks by the decompositon of the User's Query 

        Args:
            decomposition (dict[str, Any]): The decomposition of the User's Query
            project_id (UUID): The project the query corresponds to
            original_query (str): The original query the user passed in

        Returns:
            list["NodeWithScore"]: The chunks retrieved by the decomposition
        """

        if not decomposition['requires_retrieval']:
            return []

        # retrieve all chunks for each query (decomposition of users original query)
        all_chunks: list["NodeWithScore"] = []

        for item in decomposition['queries']:
            logger.info(f"Retrieving chunks for query: {item['query']}")
            
            query_chunks = await self.get_relevant_chunks(
                query=item['query'], 
                project_id=project_id,
                llm=llm
            )

            logger.info(f"Retrieved {len(query_chunks)} chunks for sub-query")
            all_chunks.extend(query_chunks)
        

        logger.debug(f"Chunks retrieved based on decomposition:\n\t{all_chunks}")
            

        # deduplicate chunks 
        deduplicated_chunks = await self.deduplicate_chunks_by_type(all_chunks)

        # rank chunks 
        ranked_chunks = await self.get_rankings(
                chunks=deduplicated_chunks,
                query=original_query,
                top_k=5 # TODO: Make this a configuration 
            )

        # return ranked chunks 
        return ranked_chunks


    async def get_relevant_chunks(
        self, 
        query: str, 
        project_id: UUID,
        llm: Any | None = None
    ) -> list["NodeWithScore"]: 
        """
        Retrieve relevant code and documentation chunks from Chroma based on the query and project ID.

        Args:
            query (str): user passed in query 
            project_id (UUID): the project the query corresponds to 
        """


        # retreive relevant Chroma Collections corresponding to Project 
        collection = self.chroma_svc.get_collection_by_project(project_id)
        if not collection:
            raise Exception(f"No ingested data found for Project ID: {project_id}")
        
        # Create embedding manager with project_id for caching
        embedding_manager = EmbeddingManager(collection, project_id=project_id)

        # load required embeddin models (with caching)
        embedding_docs = await embedding_manager.aget_embedding_model_cached()

        chunks = await self._get_chunks(query, collection, embedding_docs, llm)

        return chunks


    async def deduplicate_chunks_by_type(
        self, 
        chunks: list["NodeWithScore"]
    ) -> list["NodeWithScore"]:
        """
        Deduplicate chunks based on their content.

        Args:
            chunks (list["NodeWithScore"]): The chunks to deduplicate
        """

        # deduplicate doc chunks 
        unique_chunk_ids = set()
        unique_chunks = []

        for curr_chunk in chunks:
            if curr_chunk.id_ not in unique_chunk_ids:
                logger.debug(f"Deduplicated chunk: {curr_chunk.id_}")
                unique_chunk_ids.add(curr_chunk.id_)
                unique_chunks.append(curr_chunk)
            else:
                logger.debug(f"Duplicate chunk: {curr_chunk.id_}")
        
        return unique_chunks
    

    async def get_rankings(self, chunks: list["NodeWithScore"], query: str, top_k: int = 5) -> list["NodeWithScore"]:
        """
        Rank code and documentation chunks based on relevance to query 

        Args:
            chunks (list["NodeWithScore"]): The chunks to rank.
            query (str): The query to rank chunks against.
            top_k (int): The number of chunks to return.
        """

        logger.debug(f"Ranking top {top_k} chunks for query: {query}")

        # initialize cross encoder model 
        cross_encoder = await asyncio.to_thread(self._get_cross_encoder, settings.CROSS_ENCODING_MODEL)

        # construct pairs for cross encoder scoring
        pairs = [[query, chunk.get_content()] for chunk in chunks]

        # score & sort pairs 
        scores = cross_encoder.predict(pairs)
        scored_nodes = list(zip(chunks, scores))
        scored_nodes.sort(key=lambda x: x[1], reverse=True)

        # log re-ranked nodes for debugging
        logger.debug(f"Top ranked chunks after re-ranking: \n")
        for i, chunk in enumerate(scored_nodes):
            logger.debug(f"\tRanked Chunk {i+1}: Score={chunk[1]}, Text={chunk[0].node.get_content()}")

        return [node for node, _ in scored_nodes[:top_k]]


    def _get_cross_encoder(self, model_name: str) -> CrossEncoder:
        """
        Retrieve CrossEncoder configured in configurations in a seperate worker thread 
        in order to no block main thread with long I/O process

        TODO: Cache this model for performance gains 

        Args:
            modeL_name (str): the name of the cross encoding model 
        """
        try:

            return CrossEncoder(model_name)
        
        except Exception as e:
            logger.error(f"Failure occurred while downloading the following CrossEncoder: {model_name}", exc_info=True) 
            raise e


    async def _get_chunks(
        self, 
        query: str, 
        collection: ChromaCollection, 
        embedding: BaseEmbedding,
        llm: Any | None = None
    ) -> list["NodeWithScore"]:
        """
        Retrieve chunks directly from ChromaDB based on the query and specified collection

        Args:
            query (str): user passed in query
            collection (ChromaCollection): the Chroma collection to query against
            embedding: the LlamaIndex embedding model to use for querying
        """
        
        # configure the retrievers
        chroma_retriever = await self.get_chroma_retreiver(collection, embedding)
        bm25_retriever = await self.get_bm25_retriever(collection)

        # configure the fusion retriever (hybrid cordinator for both seamtnic and direct comparisons)
        fusion_retriever = QueryFusionRetriever(
            [chroma_retriever, bm25_retriever], 
            similarity_top_k=5,
            num_queries=3, # TODO: Determine if this is needed
            mode=FUSION_MODES.RECIPROCAL_RANK,
            use_async=True,
            llm=llm
        )

        nodes = await fusion_retriever.aretrieve(query)

        return nodes 


    async def get_bm25_retriever(self, collection: ChromaCollection) -> BaseRetriever:
        """
        Configure BM25 Retriever for Hybrid Search functionality based on all 
        nodes assocaited with Project in Postgres KV Store 

        Args:
            collection (ChromaCollection): the Chroma collection to retrieve retriever from
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

        # retrieve all nodes associated with the project (PLAIN TEXT)
        all_nodes = []
        data_source_ids = await self.get_data_source_ids_by_project(collection.project_id)
        for id in data_source_ids:
            doc_store = PostgresDocumentStore(
                kv_store, 
                namespace=str(id)
            )

            all_nodes.extend(doc_store.docs.values())
        
        # configure BM25 retreiver based on all nodes 
        return BM25Retriever.from_defaults(
            nodes=all_nodes,
            similarity_top_k=5
        )
        

    async def get_chroma_retreiver(self, collection: ChromaCollection, embedding: BaseEmbedding) -> BaseRetriever:
        """
        Get retriever associated with relevant Chroma Collection 

        Args:
            collection (ChromaCollection): the Chroma collection to retrieve retriever from
            embedding (BaseEmbedding): the LlamaIndex embedding model to use for querying
        """

        # get actual Chroma Collection 
        chroma_collection = self.chroma_svc.get_real_chroma_collection(collection_name=collection.name)

        # configure LlamaIndex retriever from Chroma collection 
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, embed_model=embedding) # pass embed_model explicitly to avoid race conditions with global Settings
        return index.as_retriever(similarity_top_k=5) # TODO: Make this configurable 
        

    async def get_data_source_ids_by_project(self, project_id: UUID) -> list[object]:
        """
        Get all data source IDs for a given project.

        Args:
            project_id (UUID): The project ID.
        """

        data_sources = self.data_source_svc.get_project_data_sources(project_id)
        data_source_ids = [data_source['id'] for data_source in data_sources]
        return data_source_ids

