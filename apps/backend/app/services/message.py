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

        
        

    async def save_message(
        self, 
        message: str, 
        sender: Sender, 
        sequence_number: int,
        content_type: str, # TODO: Create Enum for valid types 
        token_count: int,
        conversation_id: UUID
    ):
        """
        Functionality to save a message to a previously created Conversation

        Args:
            message (str): Message to be saved
            sender (Sender): Sender of the message
            sequence_number (int): Sequence number of the message
            conversation_id (UUID): ID of the conversation to save the message to
        """

        # create message in database 
        msg_to_save = Message(
            message=message,
            sender=sender,
            sequence_number=sequence_number,
            content_type=content_type,
            token_count=token_count,
            conversation_id=conversation_id
        )

        self.db.add(msg_to_save)
        await self.db.flush()

        return msg_to_save


    async def determine_question_type(self, prompt: str, formatted_messages: str, llm_manager: LLMManager) -> QuestionType: 
        """
        Determine if the current question requires new chunks to be retrieved (or if its a follow up question that can be answered using existing context)

        Args:
            prompt (str): The user's question
            formatted_messages (str): Formatted messages from the conversation, seperated by sender
            llm_manager (LLMManager): LLM Manager instance to be used for the query
        """
        
        determine_question_type_prompt = f"""
        You are a helpful assistant that determine if a user's question requires some additional context to be answered, 
        or if it can simply be answered using the existing conversation history. 

        The messages will be formatted as follows: "sender:<message>" and will be ordered by oldest to latest. 

        If you believe that the answer could be answered using the existing conversation history, return "follow_up" as the response. 
        If you believe that the answer requires new chunks to be retrieved, return "new_chunks" as the response.

        User Question: {prompt}
        Existing Messages: {formatted_messages}
        """

        llm = llm_manager.get_llm()

        try:
            logger.debug(f"Determining QuestionType for the Message={prompt}")
            response = await llm.send_message(determine_question_type_prompt)
        except Exception as e:
            logger.error(f"Error determining question type: {e}")
            return QuestionType.UNKNOWN

        return QuestionType(response.text) if response and response.text else QuestionType.UNKNOWN
        


    def get_previous_k_messages(self, conversation: Conversation, k: int = 10) -> str:
        """
        Functionality to retrieve the last k messages for a specific Conversation

        TODO: Account for differnet content types 

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


        

        