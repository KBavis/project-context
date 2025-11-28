
from app.pydantic import ChatRequest
from app.models import Conversation

from sqlalchemy.orm import Session

from uuid import UUID


class ConversationService:

    def __init__(self, db: Session):
        self.db = db 
    

    def create_conversation(self, chat: ChatRequest):
        """
        Create a new conversation with a specified LLM 

        Args:
            chat (ChatRequest): content of user sent Message and specified Project it relates to 
        """
    


    def delete_conversation(self, conversation_id: UUID):
        """
        Delete an existing conversation 

        Args:
            conversation_id (UUID): id of specified conversation to remove 
        """
    

    def update_conversation(self, chat: ChatRequest):
        """
        Continue existing conversation with specified LLM

        Args:
            chat (ChatRequest): content of user sent Message and specified Project it relates to 
        """