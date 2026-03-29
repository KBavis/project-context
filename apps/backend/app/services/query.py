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

        chunks = await self.chunk_retrieval_svc.get_relevant_chunks(query, project_id, llm=ll_model)
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
            original_query = query,
            llm=ll_model
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
        Constructs the hierarchical prompt for the LLM, clearly separating 
        instructions, conversation history, and retrieved context.
        """

        system_instructions = """
        You are a specialized AI software engineering assistant. Your role is to help users navigate and understand their specific codebase and documentation.

        ### OPERATIONAL GUIDELINES:
        1. **Codebase-Specific Questions**: 
           - Prioritize information found in the <RETRIEVED_CONTEXT> section.
           - If the provided context is completely unrelated or empty, state: "I don't have enough specific context from the codebase to answer this."
           - If the context provides partial or relevant information, answer to the best of your ability using those snippets, noting any gaps if necessary.
        2. **General Technical Knowledge**: 
           - For conceptual questions (e.g., "What is a vector database?"), provide clear explanations from your general knowledge.
           - Relate general concepts back to the <RETRIEVED_CONTEXT> whenever applicable.
        3. **Tone & Format**:
           - Professional, technically accurate, and concise.
           - Use triple backticks (e.g., ```python) for code.
           - Use **bold** for file paths and key technical terms.
        """

        # 1. Add Conversation History if it exists
        if previous_messages:
            system_instructions += f"\n\n### CONVERSATION HISTORY:\n<conversation_history>\n{previous_messages}\n</conversation_history>"

        # 2. Format Retrieved Context
        if nodes:
            context_blocks = []
            for node in nodes:
                source = node.metadata.get('source') or node.metadata.get('file_path') or "Unknown Source"
                context_blocks.append(f"Source: {source}\n---\n{node.get_text()}")
            
            context_text = "\n\n================================================================\n\n".join(context_blocks)
            retrieved_context = f"### RETRIEVED CONTEXT:\n<retrieved_context>\n{context_text}\n</retrieved_context>"
        else:
            retrieved_context = "### RETRIEVED CONTEXT:\nNo relevant documentation or code found."

        # 3. Assemble Full Prompt
        full_prompt = f"{system_instructions}\n\n{retrieved_context}\n\nUSER_QUERY: {query}\n\nAI_RESPONSE:"
        
        logger.debug(f"Complete prompt being executed: \n{full_prompt}")
        return full_prompt




    

        

        

    
    

