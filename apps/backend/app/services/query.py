from app.services.chroma import ChromaService
from app.services.ranking import RankingService
from app.core.constants import DOCS, CODE
from app.embeddings import EmbeddingManager
from app.models.collection import ChromaCollection
from app.models.question_and_answer import QuestionAndAnswer
from app.pydantic import ProcessingStatus
from app.llm import LLMManager

from sqlalchemy.ext.asyncio import AsyncSession

from typing import List
import logging
from datetime import datetime
from uuid import uuid4
import asyncio

from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import NodeWithScore

from collections import defaultdict

logger = logging.getLogger(__name__)

class QueryService:
    
    def __init__(
        self,
        db: AsyncSession,
        chroma_svc: ChromaService,
        ranking_svc: RankingService,
        llm_manager: LLMManager
    ):
        self.db = db
        self.chroma_svc = chroma_svc
        self.ranking_svc = ranking_svc
        self.llm_manager = llm_manager
    

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

        TODO: Add Context Length checks for LLM as timeouts will occurr if we provide too much context!

        Args:
            query (str): The query string to execute.
            project_id (str): The ID of the Project to query against.
        """

        try:
            # get initalized LLM instance
            llm =  self.llm_manager.get_llm() 

            # TODO: Setup async task for initalizing EmbeddingManager in order to avoid blocking main thread when first loading model weights (lazily loaded at runtime currently)
            chunks = await self.get_relevant_chunks(query, project_id)

            # re-rank retrieved chunks
            re_ranked_nodes = await self.ranking_svc.get_rankings(
                chunks=chunks,
                query=query,
                top_k=5 # TODO: Make this a configuration 
            )

            # log re-ranked nodes for debugging
            logger.debug(f"Top ranked chunks after re-ranking: \n")
            for i, chunk in enumerate(re_ranked_nodes):
                logger.debug(f"\tRanked Chunk {i+1}: Score={chunk.score}, Text={chunk.node.get_content()}")
            
            prompt = self.get_prompt(query, re_ranked_nodes)

            # configure LlamaIndex to use the selected LLM 
            Settings.llm = llm.get_llama_idx_instance()

            max_tokens = llm.get_max_context_length()
            logger.debug(f"Max Context Length for Provider={llm.provider} and Model={llm.model_name}: {max_tokens} Tokens")

            total_input_tokens = llm.tokenize(prompt)
            logger.debug(f"Total Input Tokens: {len(total_input_tokens)}")

            if len(total_input_tokens) > max_tokens:
                # TODO: Reduce number of chunks present in order to send and handle this gracefully
                raise Exception(f"Total Input Tokens ={len(total_input_tokens)}, but the the Max Tokens allowed ={max_tokens}")

            response = Settings.llm.complete(prompt) # TODO: Use LLM_EXPECTED_RESPONSE_SIZE and pass to model to ensure that we don't got over max context length 

            logger.debug(f"LLM Response: {response}")
            logger.debug(f"LLM Response Meta Data (Including Token Usage): {response.additional_kwargs}")

            # TODO: Update Q&A record with final answer and mark as COMPLETED in DB




        except Exception as e:
            logger.error(f"Error executing query for project_id={project_id} with query='{query}': {str(e)}")

            # TODO: Update Q&A record status to FAILED in DB
            raise e

        # TODO: Integrate with LLM to generate final response 

    
    def get_prompt(self, query: str, nodes: List[NodeWithScore]) -> str:
        """
        Get the prompt template to use for querying the LLM.

        TODO: Make the system prompt configurable and also consider alternative prompt template and way of providing context to LLM as this is a very basic implementation.
        """

        system_prompt = """
            You are an AI assistant that helps developers understand and work with codebases. 
            You will be provided with relevant code snippets and documentation to help answer user queries.
            Provide clear, concise, and accurate answers based on the provided code and documentation snippets.
        """

        context = "\n\n---\n\n".join([
            f"Source: {node.metadata.get('source', 'Unknown')}\n{node.get_text()}" 
            for node in nodes
        ])

        full_prompt = f"{system_prompt}\n\nContext:\n{context}\n\nUser Query: {query}\n\nAnswer:"

        return full_prompt

    async def get_relevant_chunks(self, query, project_id) -> defaultdict[str, List[NodeWithScore]]: 
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
        
        embedding_manager = EmbeddingManager(collections_by_type) # TODO: Consider injecting as dependency

        # load embedding models in parallel
        embedding_docs, embedding_code = await asyncio.gather(
            embedding_manager.aget_embedding_model(DOCS),
            embedding_manager.aget_embedding_model(CODE)
        )

        # fetch chunks in parallel
        chunks_docs, chunks_code = await asyncio.gather(
            self._get_chunks(
                query=query,
                collection=collections_by_type[DOCS],
                embedding=embedding_docs
            ),
            self._get_chunks(
                query=query,
                collection=collections_by_type[CODE],
                embedding=embedding_code
            )
        )

        # organize chunks by type
        chunks = defaultdict(list)
        chunks[DOCS] = chunks_docs
        chunks[CODE] = chunks_code

        return chunks       


    

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


    

        

        

    
    

