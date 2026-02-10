from app.models import Conversation
from app.pydantic import MessageRequest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation import ConversationService

from uuid import UUID

class MessageService:
    def __init__(
        self, 
        db: AsyncSession,
    ):
        self.db = db

        # initalize the Conversation Service 
        self.conversation_svc = self.init_conversation_svc()


    def init_conversation_svc(self):
        """
        Initialize the Conversation Service
        """
        return ConversationService(
            db=self.db,
            llm_manager=self.llm_manager
        )

    async def send_message(self, message: MessageRequest, conversation_id: UUID):
        """
        Functionality to send a message to a previously created Conversation
        """

        # retrieve conversation 
        conversation = await self.conversation_svc.get_conversation(conversation_id)
        if not conversation:
            raise Exception(f"Conversation with id {conversation_id} not found")

        # add summary to conversation if this is the first sent message 
        if conversation.summary is None:
            await self.conversation_svc.create_conversation_summary(conversation, message.content)

        # gather existing context from previously sent messages 

        # determine if this question requires new chunks to be retrieved (or if its a follow up question that can be answered using existing context)

        # retrieve relevant chunks via query service 

        # generate prompt for LLM leveraging query service 

        # send new prompt / chunks along with existing context to LLM 

        # stream response from LLM back to user 
    

    def get_previous_messages(self, conversation: Conversation):
        """
        Functionality to retrieve all previous messages for a specific Conversation

        Args:
            conversation (Conversation): Conversation to retrieve previous messages for
        """ 

        messages = conversation.messages

        # TODO: Filter messages by user and LLM 
        return None

        

        