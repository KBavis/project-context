from __future__ import annotations

from app.pydantic import CreateConversationRequest, UpdateConversationRequest
from app.models import Conversation
from app.llm.providers.base import LLMBase
from app.core import settings
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

    
    async def create_conversation_summary(self, conversation: Conversation, message: str, llm_manager: LLMManager) -> str:
        """
        Create a summary of the conversation

        Args:
            conversation (Conversation): conversation to create summary for
            message (str): message to create summary for
        """

        logger.info(f"Creating summary for conversation {conversation.id} with message {message}")

        # prompt LLM to create new summary based on users first message in conversation
        prompt = settings.LL_MODEL_CHAT_SUMMARY_SYSTEM_PROMPT + f"\n\nProject Name: {conversation.project.project_name}\n\nMessage: {message}"
        logger.debug(f"Prompt for conversation summary creation for Conversation={conversation.id}: {prompt}")

        llm = llm_manager.get_llm() 
        llm_response = await llm.send_message(prompt)

        logger.debug(f"Response from LLM for conversation summary creation for Conversation={conversation.id}: {llm_response}")

        # update Conversation record with summary 
        conversation.summary = llm_response.text

        self.db.add(conversation)
        await self.db.flush()

        return conversation.summary
        


    

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
        if model_provider not in settings.VALID_LL_MODEL_PROVIDERS:
            raise ValueError(
                f"Unsupported LLM provider '{model_provider}'. Supported providers: {sorted(settings.VALID_LL_MODEL_PROVIDERS)}"
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
            # Model lists are intentionally open-ended and can be provided by UI/user input.
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
        Delete an existing conversation 

        Args:
            conversation_id (UUID): id of specified conversation to remove 
        """
    
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