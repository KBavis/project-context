from app.services.chroma import ChromaService
from app.services.ranking import RankingService
from app.services.q_and_a import QuestionAndAnswerService
from app.core.constants import DOCS, CODE
from app.embeddings import EmbeddingManager
from app.models.collection import ChromaCollection
from app.pydantic import ProcessingStatus
from app.llm import LLMManager

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import logging
from datetime import datetime
from uuid import uuid4
import asyncio
from uuid import UUID

from llama_index.vector_stores.chroma import ChromaVectorStore # type: ignore
from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import NodeWithScore
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler

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
    

    async def execute_simple_query(self, query: str, project_id: UUID, q_and_a_record_id: UUID, start_time: datetime, llm_manager: LLMManager) -> None:
        """
        Execute a one-time query against the ingested documentation and code for a specified Project

        NOTE: This is a placeholder implementation. Down the line, relevant logic will be setup 
        to create a Converation and have multiple interactions with the LLM in one singular session.

        TODO: Refactor this logic to leverage execute_query and remove duplicate code 

        Args:
            query (str): The query string to execute.
            project_id (str): The ID of the Project to query against.
        """

        try:
            # get initalized LLM instance
            llm =  llm_manager.get_llm() 

            # TODO: In the future, we should setup a "recent projects" logic, and pre-emptively load these Embeddings into memory to speed up this call
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

            # ensure LLM limits are not being reached
            valid, _ = await llm.validate_context_length(prompt, current_token_count=0)
            if not valid:
                # TODO: Reduce number of chunks present in order to send and handle this gracefully
                raise Exception(f"Total Context Length Exceeded for Provider={llm.provider} and Model={llm.model_name}")
            
            # define call backs 
            token_counter = TokenCountingHandler(
                tokenizer=llm.tokenizer
            )
            Settings.callback_manager = CallbackManager([token_counter])

            response = await Settings.llm.acomplete(prompt) # TODO: Use LLM_EXPECTED_RESPONSE_SIZE and pass to model to ensure that we don't got over max context length 

            logger.debug(f"LLM Response: {response}")
            logger.debug(f"Total LLM Prompt Output Tokens={token_counter.completion_llm_token_count}")

            end_time = datetime.now() 

            await self.q_and_a_svc.update_q_and_a_record(
                id=q_and_a_record_id,
                output_tokens=token_counter.completion_llm_token_count,
                end_time=end_time,
                status=ProcessingStatus.SUCCESS, 
                answer=response.text, 
                total_processing_time_ms=(end_time - start_time).microseconds
            )

        except Exception as e:
            logger.error(f"Error executing query for project_id={project_id} with query='{query}': {str(e)}")

            end_time = datetime.now() 

            await self.q_and_a_svc.update_q_and_a_record(
                id=q_and_a_record_id,
                output_tokens=0,
                end_time=end_time,
                status=ProcessingStatus.FAILED,
                answer="",
                total_processing_time_ms=(end_time - start_time).microseconds
            )

            raise e

    async def execute_query(self, query: str, project_id: UUID, llm_manager: LLMManager, existing_messages: str, total_tokens: int) -> tuple[str, int]: 
        """
        Execute a query against the ingested documentation and code for a specified Project

        Args:
            query (str): The query string to execute.
            project_id (UUID): The ID of the Project to query against.
            llm_manager (LLMManager): The LLM Manager to use for the query.
            previous_messages (str): The previous messages in the conversation.
            total_tokens (int): The total number of tokens in the conversation.
        """

        llm = llm_manager.get_llm()

        # retrieve relevant chunks & re-rank 
        chunks = await self.get_relevant_chunks(query, project_id)
        re_ranked_nodes = await self.ranking_svc.get_rankings(
            chunks=chunks,
            query=query,
            top_k=5 # TODO: Make this a configuration 
        )

        # get relevant prompt 
        prompt = self.get_prompt(query, re_ranked_nodes, existing_messages)

        # configure LLM and validate 
        token_counting_handler = await self.configure_llm(llm, prompt)


        # ensure LLM limits are not being reached
        valid, total_token_count = await llm.validate_context_length(prompt, current_token_count=total_tokens)
        if not valid:
            # TODO: Reduce number of chunks present in order to send and handle this gracefully
            raise Exception(f"Total Context Length Exceeded for Provider={llm.provider} and Model={llm.model_name}")

        response = await Settings.llm.acomplete(prompt)

        return response.text, total_token_count + token_counting_handler.completion_llm_token_count


    async def configure_llm(self, llm: LLMBase, prompt: str) -> TokenCountingHandler:
        """
        Configure the LLM with the relevant prompt.

        Args:
            llm (LLM): The LLM to configure.
            prompt (str): The prompt to configure the LLM with.
        """

        # configure LlamaIndex to use the selected LLM 
        Settings.llm = llm.get_llama_idx_instance()
        
        # define call backs 
        token_counter = TokenCountingHandler(
            tokenizer=llm.tokenizer
        )
        Settings.callback_manager = CallbackManager([token_counter])

        return token_counter
    
        


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

        
    
    def get_prompt(self, query: str, nodes: list[NodeWithScore]) -> str:
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

    async def get_relevant_chunks(self, query: str, project_id: UUID) -> defaultdict[str, list[NodeWithScore]]: 
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

        # load embedding models in parallel (with caching)
        embedding_docs = await embedding_manager.aget_embedding_model_cached(DOCS)
        embedding_code = await embedding_manager.aget_embedding_model_cached(CODE)

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


    

        

        

    
    

