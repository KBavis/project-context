
from app.pydantic import CreateConversationRequest, UpdateConversationRequest
from app.models import Conversation
from app.llm.providers.base import LLMBase
from app.base import settings
from app.llm import LLMManager
from app.services.query import QueryService

from sqlalchemy.ext.asyncio import AsyncSession

from uuid import UUID, uuid4
import logging


logger = logging.getLogger(__name__)

class ConversationService:

    def __init__(
        self, 
        db: AsyncSession,
        query_svc: QueryService,
        llm_manager: LLMManager
    ):
        self.db = db 
        self.query_svc = query_svc
        self.llm_manager = llm_manager
    

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

        # retrieve the max tokens for the specified model 
        llm: LLMBase = self.llm_manager.get_llm()
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

        # download & cache embeddings for specified project 
        await self.query_svc.download_and_cache_embeddings(conversation.project_id)

        return {"id": conversation_id, "ll_model_name": model_name, "ll_model_provider": model_provider, "total_tokens": 0, "max_tokens": max_tokens}
    

        




    

    


    async def delete_conversation(self, conversation_id: UUID):
        """
        Delete an existing conversation 

        Args:
            conversation_id (UUID): id of specified conversation to remove 
        """
    

    async def update_conversation(self, conversation: UpdateConversationRequest):
        """
        Continue existing conversation with specified LLM

        Args:
            conversation (UpdateConversationRequest): content of user sent Message and specified Project it relates to 
        """