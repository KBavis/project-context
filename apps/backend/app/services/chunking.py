from sqlalchemy.ext.asyncio import AsyncSession
from sentence_transformers import CrossEncoder

from llama_index.core.schema import NodeWithScore
from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core import VectorStoreIndex

from app.services.chroma import ChromaService
from app.core import DOCS, CODE, settings
from app.embeddings import EmbeddingManager
from app.models.collection import ChromaCollection

import logging
from typing import Any
from uuid import UUID
from collections import defaultdict
import asyncio

logger = logging.getLogger(__name__)

class ChunkingService:
    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db
        self.chroma_svc: ChromaService = ChromaService(db)



    async def retrieve_chunks_by_decomposition(
        self, 
        decomposition: dict[str, Any], 
        project_id: UUID,
        original_query: str
    ) -> list[NodeWithScore]:
        """
        Retrieve chunks by the decompositon of the User's Query 

        Args:
            decomposition (dict[str, Any]): The decomposition of the User's Query
            project_id (UUID): The project the query corresponds to
            original_query (str): The original query the user passed in

        Returns:
            list[NodeWithScore]: The chunks retrieved by the decomposition
        """

        if not decomposition['requires_retrieval']:
            return []

        # retrieve all chunks for each query (decomposition of users original query)
        chunks_by_type: dict[str, list[NodeWithScore]] = {
            CODE: [],
            DOCS: []
        }

        for item in decomposition['queries']:
            logger.info(f"Retrieving chunks for query: {item['query']} from collections: {item['collections']}")

            # Case-insensitive check to be safe
            collections_upper = [c.upper() for c in item['collections']]
            needs_code = CODE in collections_upper
            needs_docs = DOCS in collections_upper
            
            query_chunks = await self.get_relevant_chunks(
                query=item['query'], 
                project_id=project_id, 
                needs_docs=needs_docs, 
                needs_code=needs_code
            )

            logger.info(f"Retrieved {len(query_chunks.get(CODE, []))} code chunks and {len(query_chunks.get(DOCS, []))} doc chunks for sub-query")
            chunks_by_type[CODE].extend(query_chunks.get(CODE, []))
            chunks_by_type[DOCS].extend(query_chunks.get(DOCS, []))
        

        logger.debug(f"Chunks retrieved based on decomposition:\nCODE CHUNKS:\n\t{chunks_by_type[CODE]}\nDOC CHUNKS:\n\t{chunks_by_type[DOCS]}")
            

        # deduplicate chunks 
        deduplicated_chunks = self.deduplicate_chunks(chunks_by_type)

        # rank chunks 
        ranked_chunks = await self.ranking_svc.get_rankings(
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
        needs_docs: bool = True, 
        needs_code: bool = True
    ) -> defaultdict[str, list[NodeWithScore]]: 
        """
        Retrieve relevant code and documentation chunks from Chroma based on the query and project ID.

        Args:
            query (str): user passed in query 
            project_id (UUID): the project the query corresponds to 
        """


        # retreive relevant Chroma Collections corresponding to Project 
        collections = self.chroma_svc.get_collections_by_project(project_id)
        if not collections:
            raise Exception(f"No ingested data found for Project ID: {project_id}")

        collections_by_type = {collection.content_type: collection for collection in collections}
        if CODE not in collections_by_type or DOCS not in collections_by_type:
            raise Exception(f"Both Code and Documentation collections must be present for Project ID: {project_id}")
        
        # Create embedding manager with project_id for caching
        embedding_manager = EmbeddingManager(collections_by_type, project_id=project_id)

        # load required embedding models (with caching)
        embedding_docs = None
        embedding_code = None

        if needs_docs:
            embedding_docs = await embedding_manager.aget_embedding_model_cached(DOCS)
        if needs_code:
            embedding_code = await embedding_manager.aget_embedding_model_cached(CODE)

        # determine which retrieval tasks are required 
        fetch_tasks: dict[str, Any] = {} 
        if needs_docs and embedding_docs:
            fetch_tasks[DOCS] = self._get_chunks(
                query=query,
                collection=collections_by_type[DOCS],
                embedding=embedding_docs
            )
        if needs_code and embedding_code:
            fetch_tasks[CODE] = self._get_chunks(
                query=query,
                collection=collections_by_type[CODE],
                embedding=embedding_code
            )
    
        # execute retrieval tasks in parallel 
        keys = list(fetch_tasks.keys())
        results = await asyncio.gather(*fetch_tasks.values())
        
        # organize results by type 
        chunks: defaultdict[str, list[NodeWithScore]] = defaultdict(list)
        for key, result in zip(keys, results):
            chunks[key] = result

        return chunks


    async def deduplicate_chunks_by_type(
        self, 
        chunks_by_type: dict[str, list[NodeWithScore]]
    ) -> dict[str, list[NodeWithScore]]:
        """
        Deduplicate chunks based on their content.

        Args:
            chunks_by_type (dict[str, list[NodeWithScore]]): The chunks to deduplicate
        """

        # deduplicate doc chunks 
        for content_type in [DOCS, CODE]:

            chunks = chunks_by_type.get(content_type, [])
            unique_chunk_ids = set()
            unique_chunks = []
            
            for curr_chunk in chunks:
                if curr_chunk.id_ not in unique_chunk_ids:
                    logger.debug(f"Deduplicated chunk: {curr_chunk.id_}")
                    unique_chunk_ids.add(curr_chunk.id_)
                    unique_chunks.append(curr_chunk)
                else:
                    logger.debug(f"Duplicate chunk: {curr_chunk.id_}")
            
            chunks_by_type[content_type] = unique_chunks
        
        return chunks_by_type
    

    async def get_rankings(self, chunks: dict[str, list[NodeWithScore]], query: str, top_k: int = 5) -> list[NodeWithScore]:
        """
        Rank code and documentation chunks based on relevance to query 

        TODO: Use CrossEncoder from LlamaIndex to determine which chunks are most relevant to user posed question 

        Args:
            code_chunks (list): List of code chunks to rank.
            doc_chunks (list): List of documentation chunks to rank.
        """

        logger.debug(f"Ranking top {top_k} chunks for query: {query}")

        # initialize cross encoder model 
        cross_encoder = await asyncio.to_thread(self._get_cross_encoder, settings.CROSS_ENCODING_MODEL)

        # construct pairs for cross encoder scoring
        all_chunks = chunks.get(CODE, []) + chunks.get(DOCS, [])
        pairs = [[query, chunk.get_content()] for chunk in all_chunks]

        # score & sort pairs 
        scores = cross_encoder.predict(pairs)
        scored_nodes = list(zip(all_chunks, scores))
        scored_nodes.sort(key=lambda x: x[1], reverse=True)

        # log re-ranked nodes for debugging
        logger.debug(f"Top ranked chunks after re-ranking: \n")
        for i, chunk in enumerate(scored_nodes):
            logger.debug(f"\tRanked Chunk {i+1}: Score={chunk[1]}, Text={chunk[0].node.get_content()}")

        return [node for node, score in scored_nodes[:top_k]]


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
        embedding: BaseEmbedding
    ) -> list[NodeWithScore]:
        """
        Retrieve chunks directly from ChromaDB based on the query and specified collection

        Args:
            query (str): user passed in query
            collection (ChromaCollection): the Chroma collection to query against
            embedding: the LlamaIndex embedding model to use for querying
        """

        # get actual Chroma Collection 
        chroma_collection = self.chroma_svc.get_real_chroma_collection(collection_name=collection.name)

        # configure LlamaIndex retriever from Chroma collection 
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, embed_model=embedding) # pass embed_model explicitly to avoid race conditions with global Settings
        retriever = index.as_retriever(similarity_top_k=5) # TODO: Make this configurable 

        # retrieve relevant chunks from collection
        nodes = await retriever.aretrieve(query)

        logger.debug(f"Retrieved {len(nodes)} chunks from collection {collection.name} for query: {query}")

        return nodes 