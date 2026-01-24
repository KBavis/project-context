
from app.pydantic import CreateConversationRequest, UpdateConversationRequest
from app.models import Conversation
from app.base import settings
from app.llm import LLMManager

from sqlalchemy.orm import Session

from uuid import UUID
import logging


logger = logging.getLogger(__name__)

class ConversationService:

    def __init__(
        self, 
        db: Session,
        llm_manager: LLMManager
    ):
        self.db = db 
        self.llm_manager = llm_manager
    

    def create_conversation(self, conversation: CreateConversationRequest):
        """
        Create a new conversation with the current configured LLM 

        Args:
            conversation (CreateConversationRequest): content of user sent Message and specified Project it relates to 
        """

        logger.info(f"Creating Conversation for project {conversation.project_id} with LLM {conversation.ll_model_name} and provider {conversation.ll_model_provider}")

        # validate llm model name and provider if passed 
        self._validate_llm_model(conversation.ll_model_name, conversation.ll_model_provider)



        # self.db.add(Conversation(
        #     project_id=conversation.project_id,
        #     ll_model_name=conversation.ll_model_name,
        #     ll_model_provider=conversation.ll_model_provider
        # ))


    def _validate_llm_model(self, model_name: str, model_provider: str):
        """
        Validate the specified LLM model name and provider OR return 
        the currently configured LLM model name and provider

        Args:
            model_name (str): name of LLM model 
            model_provider (str): provider of LLM model 
        """
        

        if model_provider not in settings.VALID_LL_MODEL_PROVIDERS:
            raise ValueError(f"Invalid LLM model provider: {model_provider}")

        
        # attempt to create LLM instance to validate model name 
        try:
            llm = self.llm_manager.get_llm()
        except ValueError as e:
            raise ValueError(f"Invalid LLM model name: {model_name}")

    
        




    

    


    def delete_conversation(self, conversation_id: UUID):
        """
        Delete an existing conversation 

        Args:
            conversation_id (UUID): id of specified conversation to remove 
        """
    

    def update_conversation(self, conversation: UpdateConversationRequest):
        """
        Continue existing conversation with specified LLM

        Args:
            conversation (UpdateConversationRequest): content of user sent Message and specified Project it relates to 
        """