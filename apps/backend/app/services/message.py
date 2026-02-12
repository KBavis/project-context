from ast import List
from app.models import Conversation
from app.pydantic import MessageRequest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation import ConversationService
from app.llm import LLMManager

from uuid import UUID
import logging

logger = logging.getLogger(__name__)

class MessageService:
    def __init__(
        self, 
        db: AsyncSession,
        conversation_svc: ConversationService
    ):
        self.db = db
        self.conversation_svc = conversation_svc


    async def send_message(self, message: MessageRequest, conversation_id: UUID):
        """
        Functionality to send a message to a previously created Conversation
        """

        # retrieve conversation 
        conversation = await self.conversation_svc.get_conversation(conversation_id)
        if not conversation:
            raise Exception(f"Conversation with id {conversation_id} not found")

        # configure LLM Manager based on Conversation -- TODO: Consider caching this LLM Manager by Conversation ID for repetetive usages (and no need to continiously reinitalize)
        llm_manager = LLMManager(model_name=conversation.ll_model_name, provider=conversation.ll_model_provider)

        # add summary to conversation if this is the first sent message 
        if conversation.summary is None:
            await self.conversation_svc.create_conversation_summary(conversation, message.content, llm_manager)

        # gather existing context from previously sent messages 
        existing_messages = self.get_previous_messages(conversation)

        # determine if this question requires new chunks to be retrieved (or if its a follow up question that can be answered using existing context)

        # retrieve relevant chunks via query service 

        # generate prompt for LLM leveraging query service 

        # send new prompt / chunks along with existing context to LLM 

        # stream response from LLM back to user 
    

    def get_previous_messages(self, conversation: Conversation) -> dict[str, List]:
        """
        Functionality to retrieve all previous messages for a specific Conversation

        Args:
            conversation (Conversation): Conversation to retrieve previous messages for
        """ 

        # ensure messages exist 
        messages = conversation.messages
        if not messages:
            return {}

        # seperate messages by sender 
        messages_by_sender = {}
        for message in messages:
            messages_by_sender[message.sender] = messages_by_sender.get(message.sender, []).append(message)

        return messages_by_sender


        

        