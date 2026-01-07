from app.services.chroma import ChromaService
from app.services.ranking import RankingService
from app.core.constants import DOCS, CODE
from app.embeddings import EmbeddingManager
from app.models.collection import ChromaCollection
from app.models.question_and_answer import QuestionAndAnswer
from app.pydantic import ProcessingStatus

from sqlalchemy.ext.asyncio import AsyncSession

from typing import List
import logging
from datetime import datetime
from uuid import uuid4

from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import NodeWithScore

logger = logging.getLogger(__name__)

class QueryService:
    
    def __init__(
        self,
        db: AsyncSession,
        chroma_svc: ChromaService,
        ranking_svc: RankingService
    ):
        self.db = db
        self.chroma_svc = chroma_svc
        self.ranking_svc = ranking_svc
    

    async def init_q_and_a_record(self, project_id: str, query: str, start_time: datetime) -> QuestionAndAnswer:
        """
        Initialize a Question & Answer record in the database.

        TODO: Consider seperating this Q&A logic into seperate service and having query service FULLY focus on LlamaIndex querying logic 

        Args:
            project_id (str): The ID of the Project being queried.
            query (str): The query string.
            start_time (datetime): The time when the query processing started.
        """

        q_and_a_pk = uuid4()

        q_and_a = QuestionAndAnswer(
            id=q_and_a_pk,
            project_id=project_id,
            question=query,
            answer="",
            start_time=start_time,
            status=ProcessingStatus.IN_PROGRESS
        )
        self.db.add(q_and_a)

        await self.db.flush()
        return q_and_a



    async def execute_simple_query(self, query: str, project_id: str) -> None:
        """
        Execute a one-time query against the ingested documentation and code for a specified Project

        NOTE: This is a placeholder implementation. Down the line, relevant logic will be setup 
        to create a Converation and have multiple interactions with the LLM in one singular session.

        Args:
            query (str): The query string to execute.
            project_id (str): The ID of the Project to query against.
        """

        try:
            
            # TODO: Setup async task for initalizing EmbeddingManager in order to
            # avoid blocking main thread when first loading model weights (lazily loaded at runtime currently)
            doc_chunks, code_chunks = await self.get_relevant_chunks(query, project_id)
            for chunks in [doc_chunks, code_chunks]:
                await self.log_chunks(chunks, chunk_type="DOCS" if chunks == doc_chunks else "CODE")

            re_ranked_chunks = await self.ranking_svc.get_rankings(
                code_chunks=code_chunks,
                doc_chunks=doc_chunks,
                query=query,
                top_k=5 # TODO: Make this a configuration 
            )
        except Exception as e:
            logger.error(f"Error executing query for project_id={project_id} with query='{query}': {str(e)}")

            # TODO: Update Q&A record status to FAILED in DB
            raise e

        # TODO: Integrate with LLM to generate final response 


    async def log_chunks(self, chunks: List[NodeWithScore], chunk_type: str):
        """
        Log retrieved chunks for debugging purposes.

        Args:
            chunks (List[NodeWithScore]): list of retrieved chunks 
            chunk_type (str): type of chunks (e.g., "DOCS" or "CODE")
        """
        logger.debug(f"Logging {len(chunks)} {chunk_type} chunks: \n")
        for i, chunk in enumerate(chunks):
            logger.debug(f"\t{chunk_type} Chunk {i+1}: Score={chunk.score}, Text={chunk.node.get_text()}")
        

    async def get_relevant_chunks(self, query, project_id): 
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
        

        embedding_manager = EmbeddingManager(collections_by_type)

        # TODO: Call _get_chunks concurrentyl for both DOCS and CODE collections  
        doc_chunks = await self._get_chunks(
            query=query,
            collection=collections_by_type[DOCS],
            embedding=embedding_manager.get_embedding_model(DOCS)
        )
        code_chunks = await self._get_chunks(
            query=query,
            collection=collections_by_type[CODE],
            embedding=embedding_manager.get_embedding_model(CODE)
        )
       
        return doc_chunks, code_chunks


    

    async def _get_chunks(self, query: str, collection: ChromaCollection, embedding: BaseEmbedding) -> List[NodeWithScore]:
        """
        Retrieve relevant documentation chunks from Chroma based on the query.

        Args:
            query (str): user passed in query
            collection (ChromaCollection): the Chroma collection to query against
            embedding: the LlamaIndex embedding model to use for querying
        """

        # get actual Chroma Collection 
        chroma_collection = self.chroma_svc.get_real_chroma_collection(collection_name=collection.name)

        # confiugre LlamaIndex to use Chroma collection embedding model
        Settings.embed_model = embedding

        # confiugre LlamaaIndex retriever from Chroma collection 
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        retriever = index.as_retriever(similarity_top_k=5) # TODO: Make this configurable 

        # retrieve relevant chunks from collection
        nodes = await retriever.aretrieve(query)

        logger.debug(f"Retrieved {len(nodes)} chunks from collection {collection.name} for query: {query}")

        return nodes 


    

        

        

    
    

