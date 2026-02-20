from app.services.chroma import ChromaService
from app.services.ranking import RankingService
from app.services.q_and_a import QuestionAndAnswerService
from app.core.constants import DOCS, CODE
from app.embeddings import EmbeddingManager
from app.models.collection import ChromaCollection
from app.pydantic import ProcessingStatus, QueryResponse
from app.llm import LLMManager, LLMBase

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
import asyncio
from uuid import UUID
from typing import Any, AsyncGenerator, Tuple
from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
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
        q_and_a_svc: QuestionAndAnswerService,
    ):
        self.db: AsyncSession = db
        self.chroma_svc: ChromaService = chroma_svc
        self.ranking_svc: RankingService = ranking_svc
        self.q_and_a_svc: QuestionAndAnswerService = q_and_a_svc
    

    async def execute_q_and_a_query(self, query: str, project_id: UUID, q_and_a_record_id: UUID, start_time: datetime, llm_manager: LLMManager) -> None:
        """
        Execute a one-time query against the ingested documentation and code for a specified Project

        NOTE: This is a placeholder implementation. Down the line, relevant logic will be setup 
        to create a Converation and have multiple interactions with the LLM in one singular session.

        Args:
            query (str): The query string to execute.
            project_id (UUID): The ID of the Project to query against.
            q_and_a_record_id (UUID): The ID of the Q&A record to update.
            start_time (datetime): The start time of the query.
            llm_manager (LLMManager): The LLM Manager to use for the query.
        """

        try:
            # Execute query using the generic implementation (no existing messages or tokens for simple query)
            response: QueryResponse = await self.execute_query(
                query=query,
                project_id=project_id,
                llm_manager=llm_manager,
                existing_messages="",  # No conversation history for simple queries
                existing_tokens=0  # Starting from zero tokens
            )

            logger.debug(f"LLM Response: {response.model_response}")
            logger.debug(f"Total Token Count: {response.total_tokens}")

            end_time = datetime.now(ZoneInfo("America/New_York")) 

            await self.q_and_a_svc.update_q_and_a_record(
                id=q_and_a_record_id,
                output_tokens=response.model_output_tokens,
                end_time=end_time,
                status=ProcessingStatus.SUCCESS, 
                answer=response.model_response, 
                total_processing_time_ms=(end_time - start_time).microseconds
            )

        except Exception as e:
            logger.error(f"Error executing query for project_id={project_id} with query='{query}': {str(e)}")

            end_time = datetime.now(ZoneInfo("America/New_York")) 

            await self.q_and_a_svc.update_q_and_a_record(
                id=q_and_a_record_id,
                output_tokens=0,
                end_time=end_time,
                status=ProcessingStatus.FAILED,
                answer="",
                total_processing_time_ms=(end_time - start_time).microseconds
            )

            raise e


    async def execute_query(self, query: str, project_id: UUID, llm_manager: LLMManager, decomposition: dict[str, Any] | None = None, existing_messages: str = "", existing_tokens: int = 0) -> QueryResponse: 
        """
        Execute a query against the ingested documentation and code for a specified Project

        Args:
            query (str): The query string to execute.
            project_id (UUID): The ID of the Project to query against.
            llm_manager (LLMManager): The LLM Manager to use for the query.
            decomposition (dict[str, Any]): The decomposition of the users original query.
            existing_messages (str): The previous messages in the conversation.
            existing_tokens (int): The total number of tokens in the conversation.
        """

        llm = llm_manager.get_llm()
        ll_model = llm.get_llama_idx_instance()

        prompt, user_prompt_tokens = await self._prepare_query_context(
            query=query,
            project_id=project_id,
            llm=llm,
            decomposition=decomposition,
            existing_messages=existing_messages,
            existing_tokens=existing_tokens
        )

        # NOTE: Using acomplete for standard query
        response = await ll_model.acomplete(prompt)

        # calculate exact output tokens from the response text
        model_output_tokens = len(await llm.tokenize(response.text))

        return QueryResponse(
            user_prompt=query,
            model_response=response.text,
            user_input_tokens=user_prompt_tokens,
            model_output_tokens=model_output_tokens,
            total_tokens = existing_tokens + user_prompt_tokens + model_output_tokens
        )


    async def execute_query_stream(self, query: str, project_id: UUID, llm_manager: LLMManager, decomposition: dict[str, Any] | None = None, existing_messages: str = "", existing_tokens: int = 0) -> AsyncGenerator[str, None]:
        """
        Execute a streaming query against the ingested documentation and code.
        """
        llm = llm_manager.get_llm()
        ll_model = llm.get_llama_idx_instance()

        prompt, _ = await self._prepare_query_context(
            query=query,
            project_id=project_id,
            llm=llm,
            decomposition=decomposition,
            existing_messages=existing_messages,
            existing_tokens=existing_tokens
        )

        response_gen = await ll_model.astream_complete(prompt)

        async for chunk in response_gen:
            if chunk.delta:
                yield chunk.delta


    async def _prepare_query_context(self, query: str, project_id: UUID, llm: LLMBase, decomposition: dict[str, Any] | None = None, existing_messages: str = "", existing_tokens: int = 0) -> Tuple[str, int]:
        """
        Helper to prepare the prompt and context for both sync and streaming queries.
        """
        # tokenize user prompt (excluding message history & system prompt)
        user_prompt_tokens = len(await llm.tokenize(query))

        # retrieve relevant chunks & re-rank 
        if decomposition:
            nodes = await self.get_all_chunks(decomposition, project_id, query)
            logger.info(f"Retrieved {len(nodes)} chunks after decomposition and ranking.")
        else:
            logger.info(f"Retrieving relevant chunks for project {project_id} and query '{query}'")
            chunks = await self.get_relevant_chunks(query, project_id)
            nodes = await self.ranking_svc.get_rankings(
                chunks=chunks,
                query=query,
                top_k=5 # TODO: Make this a configuration 
            )
            logger.info(f"Retrieved {len(nodes)} chunks after ranking for project {project_id}.")

        # get relevant prompt & populate with context retrieved via RAG
        prompt = self.get_prompt(query, nodes, existing_messages)

        # NOTE: Leverage 'prompt' instead of 'query' for validation (in order to account for conversation history bloat)
        valid = await llm.validate_context_length(prompt, current_token_count=existing_tokens)
        if not valid:
            raise Exception(f"Total Context Length Exceeded for Provider={llm.provider} and Model={llm.model_name}")

        return prompt, user_prompt_tokens


    async def download_and_cache_embeddings(self, project_id: UUID) -> None:
        """
        Download and cache embeddings for a specified project.
        
        This preloads embedding models into memory cache to improve 
        response time for subsequent queries on this project.

        TODO: Conisder if this belongs in ChromaService or EmbeddingManager 
        
        Args:
            project_id (UUID): The project ID to cache embeddings for
        """
        try:
            # retreive relevant Chroma Collections corresponding to Project 
            collections = self.chroma_svc.get_collections_by_project(project_id)
            if not collections:
                logger.warning(f"No ingested data found for Project ID: {project_id}")
                return

            collections_by_type = {collection.content_type: collection for collection in collections}
            if CODE not in collections_by_type or DOCS not in collections_by_type:
                logger.warning(f"Both Code and Documentation collections must be present for Project ID: {project_id}")
                return
            
            # Create embedding manager with project_id for caching
            embedding_manager = EmbeddingManager(collections_by_type, project_id=project_id)

            # Pre-load and cache both embedding models in parallel
            logger.info(f"Pre-loading and caching embeddings for project {project_id}...")
            await asyncio.gather(
                embedding_manager.aget_embedding_model_cached(DOCS),
                embedding_manager.aget_embedding_model_cached(CODE)
            )
            logger.info(f"Successfully cached embeddings for project {project_id}")
            
        except Exception as e:
            logger.error(f"Error caching embeddings for project {project_id}: {str(e)}")
            # Don't raise - caching is a performance optimization, not critical

    
    async def get_all_chunks(self, decomposition: dict[str, Any], project_id: UUID, query: str) -> list[NodeWithScore]:
        """
        Retrieve all relevant chunks from Chroma based on the decomposition of the query.

        Args:
            decomposition (dict[str, Any]): The decomposition of the query
            project_id (UUID): The project ID to retrieve chunks for
            query (str): The query to retrieve chunks for
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
                query=query,
                top_k=5 # TODO: Make this a configuration 
            )

        # return ranked chunks 
        return ranked_chunks


        

    def deduplicate_chunks(self, chunks_by_type: dict[str, list[NodeWithScore]]) -> dict[str, list[NodeWithScore]]:
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
                
    
    def get_prompt(self, query: str, nodes: list[NodeWithScore] | None = None, previous_messages: str = "") -> str:
        """
        Get the prompt template to use for querying the LLM.

        TODO: Make the system prompt configurable and also consider alternative prompt template and way of providing context to LLM as this is a very basic implementation.
        """

        system_prompt = """
            You are an AI assistant that helps developers understand and work with codebases. 
            You will be provided with relevant code snippets and documentation to help answer user queries.
            Provide clear, concise, and accurate answers based on the provided code and documentation snippets.
            If the answer is not in the provided code and documentation snippets, say so and do not make up an answer.
        """

        if previous_messages:
            system_prompt += f"\n\n<context>\nPrevious Messages in this Conversation (in format user:<message> and model:<message> and sorted in oldest to latest order):\n{previous_messages}\n</context>"

        if nodes:
            context = "\n\n---\n\n".join([
                f"Source: {node.metadata.get('source', 'Unknown')}\n{node.get_text()}" 
                for node in nodes
            ])
        else:
            context = "No context provided"

        full_prompt = f"{system_prompt}\n\nContext:\n{context}\n\nUser Query: {query}\n\nAnswer:"

        return full_prompt

    async def get_relevant_chunks(self, query: str, project_id: UUID, needs_docs: bool = True, needs_code: bool = True) -> defaultdict[str, list[NodeWithScore]]: 
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


    

    async def _get_chunks(self, query: str, collection: ChromaCollection, embedding: BaseEmbedding) -> list[NodeWithScore]:
        """
        Retrieve relevant documentation chunks from Chroma based on the query.

        Args:
            query (str): user passed in query
            collection (ChromaCollection): the Chroma collection to query against
            embedding: the LlamaIndex embedding model to use for querying
        """

        # get actual Chroma Collection 
        chroma_collection = self.chroma_svc.get_real_chroma_collection(collection_name=collection.name)

        # configure LlamaIndex retriever from Chroma collection 
        # Pass embed_model explicitly to avoid race conditions with global Settings
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, embed_model=embedding)
        retriever = index.as_retriever(similarity_top_k=5) # TODO: Make this configurable 

        # retrieve relevant chunks from collection
        nodes = await retriever.aretrieve(query)

        logger.debug(f"Retrieved {len(nodes)} chunks from collection {collection.name} for query: {query}")

        return nodes 


    

        

        

    
    

