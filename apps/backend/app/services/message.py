from datetime import datetime
from enum import Enum
from app.models import Conversation, Sender

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.conversation import ConversationService
from app.services.query import QueryService
from app.models import Message
from app.llm import LLMManager
from app.pydantic import QueryResponse, PromptResponse, MessageDto, MessageRequest

from uuid import UUID
import heapq
import logging

logger = logging.getLogger(__name__)

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

    
    async def get_messages(self, conversation_id: UUID):
        """
        Functionality to get all messages for a conversation

        Args:
            conversation_id (UUID): ID of the conversation to get messages for
        """

        messages = await self.db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.sequence_number)
        )
        return messages.scalars().all()


    async def send_message(self, message: MessageRequest, conversation_id: UUID) -> PromptResponse:
        """
        Functionality to send a message to a previously created Conversation

        TODO: Look into streaming this response back to the user and sending periodic updates so front-end 
        knows the current state 

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


        # TODO: Remove QuestionType and Determine Question Type function in favor of using decomposition of queries 
        llm = llm_manager.get_llm()
        decomposition_result = await llm.decompose_query(message.content, existing_messages)
        logger.debug(f"Decomposition Result for the Conversation={conversation_id} and Message={message.content}: {decomposition_result}")

        query_result = await self.query_svc.execute_query(
            query=message.content, 
            project_id=conversation.project_id, 
            llm_manager=llm_manager, 
            decomposition=decomposition_result, 
            existing_messages=existing_messages, 
            existing_tokens=conversation.total_tokens
        )

        
        logger.debug(f"Query Result for the Conversation={conversation_id} and Message={message.content}: {query_result.model_response}")
        logger.debug(f"Total Token Count for the Conversation={conversation_id} and Message={message.content}: {query_result.total_tokens}")

        # persist updates to Message & Conversation
        user_msg, model_msg = await self.save_messages(
            query_result, 
            conversation_id, 
            message.content_type, 
            len(existing_messages)
        )
        await self.conversation_svc.update_total_tokens(conversation_id, query_result.total_tokens)

        return PromptResponse(
            user_message=self._get_message_dto(user_msg),
            model_message=self._get_message_dto(model_msg),
            conversation_id=conversation_id
        ) 


        # stream response from LLM back to user 
    
    def _get_message_dto(self, message: Message) -> MessageDto:
        return MessageDto(
            content=message.content,
            content_type=message.content_type,
            token_count=message.token_count,
            sequence_number=message.sequence_number,
            created_at=message.created_at,
            updated_at=message.updated_at
        )

        
    async def save_messages(
        self, 
        query_result: QueryResponse, 
        conversation_id: UUID, 
        message_content_type: str, 
        existing_messages_length: int
    ) :
        """
        Functionality to save a message to a previously created Conversation

        Args:
            query_result (QueryResponse): Query result from the conversation
            conversation_id (UUID): ID of the conversation to save the message to
            message_content_type (str): Content type of the message
        """

        # calculate sequence numbers (user ask, model respond)
        user_sequence_number = existing_messages_length + 1 
        model_sequence_number = user_sequence_number + 1

        # save user and model messages
        user_msg = await self.save_message(
            message=query_result.user_prompt,
            sender=Sender.USER,
            sequence_number=user_sequence_number,
            content_type=message_content_type,
            token_count=query_result.user_input_tokens,
            conversation_id=conversation_id
        )
        model_msg = await self.save_message(
            message=query_result.model_response,
            sender=Sender.MODEL,
            sequence_number=model_sequence_number,
            content_type="text", # TODO: Use enum and account for potential types 
            token_count=query_result.model_output_tokens,
            conversation_id=conversation_id
        )

        logger.debug(f"Saved User & Model Messages for Conversation={conversation_id} and User Prompt='{query_result.user_prompt}' and Model Response='{query_result.model_response}'")

        return user_msg, model_msg


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
            content=message,
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
            You are a classifier that determines whether a user's question can be answered using existing conversation history, or requires retrieving new information.

            MESSAGES FORMAT: "sender:<message>", ordered oldest to latest.

            CLASSIFICATION RULES:
            - Return "new_chunks" if the question introduces any new topic, entity, or concept not already discussed in the conversation history.
            - Return "new_chunks" if you are uncertain which to choose.
            - Return "follow_up" ONLY if you are highly confident the question can be fully answered from the existing messages alone (e.g. "can you clarify what you said?", "summarize the above", "what did you mean by X?" where X was already explained).

            IMPORTANT: When in doubt, always return "new_chunks". It is better to retrieve unnecessary context than to fail to answer due to missing information.

            User Question: {prompt}
            Existing Messages: {formatted_messages}

            Respond with only "follow_up" or "new_chunks".
        """

        llm = llm_manager.get_llm()

        try:
            logger.debug(f"Determining QuestionType for the Message={prompt}\nLLM Prompt: {determine_question_type_prompt}")
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


    

        

        