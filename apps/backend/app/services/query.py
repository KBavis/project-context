from __future__ import annotations
from app.services.chroma import ChromaService
from app.services.chunk_retrieval import ChunkRetrievalService
from app.pydantic import ProcessingStatus, QueryResponse
from app.llm import LLMManager, LLMBase

from sqlalchemy.ext.asyncio import AsyncSession

import logging
from uuid import UUID
from typing import Any, AsyncGenerator, Tuple
from llama_index.core.schema import NodeWithScore


logger = logging.getLogger(__name__)

class QueryService:
    
    def __init__(
        self,
        db: AsyncSession,
        chunk_retrieval_svc: ChunkRetrievalService,
    ):
        self.db: AsyncSession = db
        self.chunk_retrieval_svc: ChunkRetrievalService = chunk_retrieval_svc


    async def execute_query(self, query: str, project_id: UUID, llm_manager: LLMManager, decomposition: dict[str, Any] | None = None, existing_messages: str = "", existing_tokens: int = 0) -> QueryResponse: 
        """
        Execute a query against the ingested documentation and code for a specified Project

        NOTE: This is only leveraged via `execute_q_and_q_query` and `send_message_sync`, but the preferred execution of queries 
        is `execute_query_stream`. This can be removed down the line

        Args:
            query (str): The query string to execute.
            project_id (UUID): The ID of the Project to query against.
            llm_manager (LLMManager): The LLM Manager to use for the query.
            decomposition (dict[str, Any]): The decomposition of the users original query.
            existing_messages (str): The previous messages in the conversation.
            existing_tokens (int): The total number of tokens in the conversation.
        """

        logger.info(f"Executing query for project {project_id}: {query}")

        llm = llm_manager.get_llm()
        ll_model = llm.get_llama_idx_instance()

        user_prompt_tokens = len(await llm.tokenize(query))

        chunks = await self.chunk_retrieval_svc.get_relevant_chunks(query, project_id)
        nodes = await self.chunk_retrieval_svc.get_rankings(
            chunks=chunks,
            query=query,
            top_k=5 # TODO: Make this a configuration 
        )
        logger.info(f"Retrieved {len(nodes)} chunks after ranking for project {project_id}.")

        # get relevant prompt & populate with context retrieved via RAG
        prompt = self.get_prompt(query, nodes, existing_messages)

        # NOTE: Leverage 'prompt' instead of 'query' for validation (in order to account for conversation history & system prompt bloat)
        valid = await llm.validate_context_length(prompt, current_token_count=existing_tokens)
        if not valid:
            raise Exception(f"Total Context Length Exceeded for Provider={llm.provider} and Model={llm.model_name}")

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
        

    async def execute_query_stream(
        self, 
        query: str, 
        project_id: UUID, 
        llm_manager: LLMManager,
        decomposition: dict[str, Any], 
        existing_messages: str = "", 
        existing_tokens: int = 0
    ) -> Tuple[list["NodeWithScore"], AsyncGenerator[str, None]]:
        """
        Send user's decomposed query to the configured LLM, utilizing the Conversation History & 
        chunked ingested Code/Documentation files as context, and stream the response 
        back to the calling function in chunks

        Args:
            query (str): The users original prompt.
            project_id (UUID): The ID of the Project to query against.
            llm_manager (LLMManager): The LLM Manager to use for the query.
            decomposition (dict[str, Any]): The decomposition of the users original query.
            existing_messages (str): The previous messages in the conversation.
            existing_tokens (int): The total number of tokens in the conversation.
        """

        llm = llm_manager.get_llm()
        ll_model = llm.get_llama_idx_instance()
        
        # retrieve relevant chunks based on decomposed query 
        relevant_chunks = await self.chunk_retrieval_svc.retrieve_chunks_by_decomposition(
            decomposition, 
            project_id,
            original_query = query
        )

        # generate prompt using additional context & conversation history 
        prompt = self.get_prompt(
            query,
            relevant_chunks,
            existing_messages
        )

        # valid context length against prompt 
        valid = await llm.validate_context_length(prompt, current_token_count=existing_tokens) # NOTE: Leverage 'prompt' instead of 'query' for validation (account for conversation history & system prompt bloat)
        if not valid:
            raise Exception(f"Total Context Length Exceeded for Provider={llm.provider} and Model={llm.model_name}")

        # generator for streaming LLM response back to invoking user 
        async def llm_token_generator():
            response_gen = await ll_model.astream_complete(prompt)
            async for chunk in response_gen:
                if chunk.delta:
                    yield chunk.delta

        return relevant_chunks, llm_token_generator()


    
    def get_prompt(self, query: str, nodes: list["NodeWithScore"] | None = None, previous_messages: str = "") -> str:
        """
        Get the prompt template to use for querying the LLM.

        TODO: Make the system prompt configurable and also consider alternative prompt template and way of providing context to LLM as this is a very basic implementation.
        """

        system_prompt = """
        You are a specialized AI software engineering assistant. Your primary goal is to help users understand their specific codebase using the provided "Context" and "Previous Messages".

        GUIDELINES:
        1. **Codebase Specifics (Priority)**: When asked about the implementation, architecture, or logic of this specific project, you MUST strictly rely on the provided Context. If the Context is insufficient for a project-specific question, say: "I don't have enough specific context from the codebase to answer this project-specific question."
        2. **General Technical Knowledge**: If a user asks a general conceptual or technical question (e.g., "What is Docker?", "How does a vector database work?"), you should provide a clear and helpful explanation using your general knowledge, even if it is not in the provided Context.
        3. **Context Sensitivity**: Use the Context to ground your answers whenever possible. If the user asks about a general concept in the context of their project, relate your general knowledge back to the information provided in the codebase snippets.
        4. **Markdown Formatting**:
           - Use triple backticks with the language identifier (e.g., ```python) for all code snippets.
           - Use **bold** for file paths, variable names, and key technical concepts.
           - Use headers and lists to structure complex explanations.
        5. **Tone**: Professional, concise, and technically accurate.
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
        logger.debug(f"Complete prompt being executed: \n{full_prompt}")

        return full_prompt



    

        

        

    
    

