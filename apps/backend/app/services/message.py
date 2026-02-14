from ast import List
from app.models import Conversation
from app.pydantic import MessageRequest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation import ConversationService
from app.llm import LLMManager

from uuid import UUID
import heapq
import logging

logger = logging.getLogger(__name__)

class QuestionType(Enum):
    NEW_CHUNKS = "new_chunks"
    FOLLOW_UP = "follow_up"
    UNKNOWN = "unknown"

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


    async def send_message(self, message: MessageRequest, conversation_id: UUID):
        """
        Functionality to send a message to a previously created Conversation

        Args:
            message (MessageRequest): Message to be sent
            conversation_id (UUID): ID of the conversation to send the message to
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
        existing_messages = self.get_previous_k_messages(conversation)
        if not existing_messages:
            logger.warning(f"No existing messages found for conversation {conversation_id}")


        # determine if this question requires new chunks to be retrieved (or if its a follow up question that can be answered using existing context)
        question_type = await self.determine_question_type(message.content, existing_messages, llm_manager)
        if question_type == QuestionType.UNKNOWN:
            logger.error(f"Could not determine question type for conversation {conversation_id}")
            raise Exception("Could not determine question type")


        logger.debug(f"QuestionType for the Conversation={conversation_id} and Message={message.content}: {question_type.value}")        

        if question_type == QuestionType.NEW_CHUNKS:
            query_result, output_token_count = await self.query_svc.execute_query(message.content, conversation.project_id, llm_manager, existing_messages, conversation.total_tokens)

            logger.debug(f"Query Result for the Conversation={conversation_id} and Message={message.content}: {query_result}")
            logger.debug(f"Total Token Count for the Conversation={conversation_id} and Message={message.content}: {output_token_count}")

            # TODO: Update conversation total tokens 
        elif question_type == QuestionType.FOLLOW_UP:  

            # TODO: Configure logic to handle follow up questions 
            logger.debug(f"Follow up question for the Conversation={conversation_id} and Message={message.content}") 
            
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
            k (int): Number of previous messages to retrieve
        """ 

        # ensure messages exist 
        messages = conversation.messages
        if not messages:
            return ""

        # retrieve converastion history and filter out older messages 
        min_heap  = [] 
        for message in messages:
            heapq.heappush(
                min_heap, 
                (message.sequence_number, f"{message.sender.value}:{message.content}")
            )

            if len(min_heap) > k:
                heapq.heappop(min_heap)
        
        # filter out message content & token count 
        k_messages = [message[1] for message in min_heap]

        # transform into a string 
        return "\n".join(k_messages)


    

        

        