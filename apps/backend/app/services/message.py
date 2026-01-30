from app.pydantic import MessageRequest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation import ConversationService
from app.services.query import QueryService

from uuid import UUID

class MessageService:
    def __init__(
        self, 
        db: AsyncSession,
        conversation_svc: ConversationService,
        query_svc: QueryService
    ):
        self.db = db
        self.conversation_svc = conversation_svc
        self.query_svc = query_svc

    def send_message(self, message: MessageRequest, conversation_id: UUID):
        """
        Functionality to send a message to a previously created Conversation
        """

        # retrieve conversation 
        conversation = self.conversation_svc.get_conversation(conversation_id)
        if not conversation:
            raise Exception(f"Conversation with id {conversation_id} not found")

        
        # gather existing context from previously sent messages 

        # add summary to conversation if this is the first sent message 

        # determine if this question requires new chunks to be retrieved (or if its a follow up question that can be answered using existing context)

        # retrieve chunks via query service 

        # generate prompt for LLM leveraging query service 

        # send new prompt / chunks along with existing context to LLM 

        # stream response from LLM back to user 


        

        