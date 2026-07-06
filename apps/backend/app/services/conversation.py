from __future__ import annotations

from app.pydantic import CreateConversationRequest, UpdateConversationRequest
from app.models import Conversation
from app.llm.providers.base import LLMBase
from app.core import settings, VALID_LL_MODEL_PROVIDERS
from app.llm import LLMManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from uuid import UUID, uuid4
import logging


logger = logging.getLogger(__name__)

class ConversationService:

    def __init__(
        self, 
        db: AsyncSession,
    ):
        self.db = db 

    
    async def generate_summary_text(self, project_name: str, message: str, llm_manager: LLMManager) -> str:
        """
        Generate a short conversation title from the user's first message.

        This performs ONLY the LLM call (no DB writes) so it can run concurrently with
        the agentic workflow; the caller is responsible for persisting the returned text.

        Args:
            project_name (str): name of the project the conversation is scoped to
            message (str): the user's first message
            llm_manager (LLMManager): manager used to resolve the conversation's LLM
        """
        prompt = settings.LL_MODEL_CHAT_SUMMARY_SYSTEM_PROMPT + f"\n\nProject Name: {project_name}\n\nMessage: {message}"

        llm = llm_manager.get_llm()
        # Low temperature keeps titles stable and short rather than drifting into verbose summaries.
        llm_response = await llm.send_message(prompt, temperature=0.2)

        return (llm_response.text or "").strip()
        


    

    async def create_conversation(self, conversation: CreateConversationRequest):
        """
        Create a new conversation with the current configured LLM 

        NOTE: We do not validate the LLM model name and provider here as we expect the LLMManager to handle this 

        Args:
            conversation (CreateConversationRequest): content of user sent Message and specified Project it relates to 
        """

        logger.info(f"Creating Conversation for project {conversation.project_id} with LLM {conversation.ll_model_name} and provider {conversation.ll_model_provider}")

        # Use settings defaults if not provided
        model_name = conversation.ll_model_name or settings.LL_MODEL
        model_provider = conversation.ll_model_provider or settings.LL_MODEL_PROVIDER

        # Validate provider/model selection before creating LLM client
        if model_provider not in VALID_LL_MODEL_PROVIDERS:
            raise ValueError(
                f"Unsupported LLM provider '{model_provider}'. Supported providers: {sorted(VALID_LL_MODEL_PROVIDERS)}"
            )

        # Configure LLM Manager based on validated request parameters
        llm_manager = LLMManager(
            model_name=model_name,
            provider=model_provider
        )

        # retrieve the max tokens for the specified model 
        llm: LLMBase = llm_manager.get_llm()
        max_tokens = await llm.get_max_context_length() 

        # create conversation record 
        conversation_id = uuid4()
        self.db.add(Conversation(
            id=conversation_id,
            project_id=conversation.project_id,
            ll_model_name=model_name,
            ll_model_provider=model_provider,
            total_tokens=0,
            max_tokens=max_tokens,
        ))
        await self.db.flush() 

        return {"id": conversation_id, "ll_model_name": model_name, "ll_model_provider": model_provider, "total_tokens": 0, "max_tokens": max_tokens}

    async def get_llm_options(self) -> dict[str, list[str]]:
        """
        Return selectable provider -> models map for UI consumption.
        """
        return {
            # Azure gateway routes GPT, Claude, Gemini, etc.
            "Azure": [],
            # Direct OpenAI API access.
            "OpenAI": [],
            # Ollama models are environment-dependent and discovered at runtime.
            "Ollama": [],
        }
    

    async def get_conversation(self, conversation_id: UUID):
        """
        Retrieve an existing conversation 

        Args:
            conversation_id (UUID): id of specified conversation to retrieve 
        """
        stmt = (
            select(Conversation)
            .options(
                selectinload(Conversation.messages),
                selectinload(Conversation.project)
            )
            .where(Conversation.id == conversation_id)
        )
        conversation = await self.db.execute(stmt)
        return conversation.scalar_one_or_none()


    async def get_all_conversations(self) -> list[Conversation]:
        """
        Retrieve all conversations
        """
        stmt = (
            select(Conversation)
            .options(
                selectinload(Conversation.messages),
                selectinload(Conversation.project)
            )
            .order_by(Conversation.updated_at.desc()) 
        )
        conversations = await self.db.execute(stmt)
        return list(conversations.scalars().all())

    


    async def delete_conversation(self, conversation_id: UUID):
        """
        Delete an existing conversation along with its messages and token-usage
        records (removed via the relationship cascades on the Conversation model).
        
        Args:
            conversation_id (UUID): id of specified conversation to remove 
        """
        conversation = await self.get_conversation(conversation_id)
        if not conversation:
            raise Exception(f"Conversation with id {conversation_id} not found")
        await self.db.delete(conversation)
        await self.db.flush()
    
    async def update_total_tokens(self, conversation_id: UUID, token_count: int):
        """
        Update the total token count for a conversation

        Args:
            conversation_id (UUID): id of specified conversation to update
            token_count (int): token count to add to the conversation
        """
        conversation = await self.get_conversation(conversation_id)
        if not conversation:
            raise Exception(f"Conversation with id {conversation_id} not found")
        conversation.total_tokens += token_count
        self.db.add(conversation)
        await self.db.flush()
    
    async def update_total_execution_tokens(self, conversation_id: UUID, token_count: int):
        """
        Update the total execution token count for a conversation

        Args:
            conversation_id (UUID): id of specified conversation to update
            token_count (int): token count to add to the conversation
        """
        conversation = await self.get_conversation(conversation_id)
        if not conversation:
            raise Exception(f"Conversation with id {conversation_id} not found")
        conversation.total_execution_tokens += token_count
        self.db.add(conversation)
        await self.db.flush()
    


    async def update_conversation(self, conversation: UpdateConversationRequest):
        """
        Continue existing conversation with specified LLM

        Args:
            conversation (UpdateConversationRequest): content of user sent Message and specified Project it relates to 
        """