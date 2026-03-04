from datetime import datetime
from enum import Enum

from llama_index.core.schema import NodeWithScore
from llama_index.core.vector_stores.types import NodeWithEmbedding
from app.models import Conversation, Sender

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.pydantic.file import FileCitation
from app.services.conversation import ConversationService
from app.services.citations import CitationService
from app.services.query import QueryService
from app.models import Message
from app.llm import LLMBase, LLMManager
from app.pydantic import QueryResponse, PromptResponse, MessageDto, MessageRequest

from uuid import UUID
import heapq
import logging
from typing import Any, AsyncGenerator
from app.pydantic.streaming import StreamEvent, StreamEventType


logger = logging.getLogger(__name__)

class MessageService:
    def __init__(
        self, 
        db: AsyncSession,
        conversation_svc: ConversationService,
        query_svc: QueryService,
        citation_svc: CitationService
    ):
        self.db = db
        self.conversation_svc = conversation_svc
        self.query_svc = query_svc
        self.citation_svc = citation_svc

    
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


    async def sync_send_message(self, message: MessageRequest, conversation_id: UUID) -> PromptResponse:
        """
        Functionality to send a message to a previously created Conversation synchronously 

        NOTE: Sending a message via streaming capabilities is stypically the preferred method, but this functionality 
        can be leveraged for testing purposes 

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
            len(conversation.messages)
        )
        await self.conversation_svc.update_total_tokens(conversation_id, query_result.total_tokens)

        return PromptResponse(
            user_message=self._get_message_dto(user_msg),
            model_message=self._get_message_dto(model_msg),
            conversation_id=conversation_id
        ) 



    async def send_message_stream(self, message: MessageRequest, conversation_id: UUID) -> AsyncGenerator[str, None]:
        """
        Stream the message response back to the user, providing intermediate status updates.

        Args:
            message (MessageRequest): users prompt 
            conversation_id (UUID): ID of the conversation to send the message to
        
        Yields:
            str: SSE formatted event with intermediate status updates
        """
        try:
            # 1. Initialize 
            yield self._format_sse_event(StreamEventType.STATUS, "Initializing conversation context...", "Initializing")
            
            conversation = await self.conversation_svc.get_conversation(conversation_id)
            if not conversation:
                yield self._format_sse_event(StreamEventType.ERROR, f"Conversation {conversation_id} not found", "Error")
                return

            llm_manager = LLMManager(model_name=conversation.ll_model_name, provider=conversation.ll_model_provider)
            llm = llm_manager.get_llm()

            # 2. Generate Conversation Summary (if needed)
            if conversation.summary is None:
                logger.info(f"Conversation {conversation_id} has no summary, generating one...")
                yield self._format_sse_event(StreamEventType.STATUS, "Generating conversation summary...", "Summarizing")
                await self.conversation_svc.create_conversation_summary(conversation, message.content, llm_manager)

            # 3. Retrieve Conversation History & Decompose Query If Needed
            existing_messages = self.get_previous_k_messages(conversation)
            if not existing_messages:
                logger.debug(f"No existing messages found for conversation {conversation_id}")
            
            yield self._format_sse_event(StreamEventType.STATUS, "Analyzing query and retrieving context...", "Retrieving")
            decomposition_result = await llm.decompose_query(message.content, existing_messages)
            logger.info(f"Decomposition Result for the Conversation={conversation_id}: {decomposition_result}")
            
            # 4. Prompt LLM and retrieve relevant context
            yield self._format_sse_event(StreamEventType.STATUS, "Generating response...", "Generating")
            logger.info(f"Starting LLM Stream for the Conversation={conversation_id}")

            chunks, llm_response_stream = await self.query_svc.execute_query_stream(
                query=message.content,
                project_id=conversation.project_id,
                llm_manager=llm_manager,
                decomposition=decomposition_result,
                existing_messages=existing_messages,
                existing_tokens=conversation.total_tokens
            )
            full_response = ""
            async for token in llm_response_stream:
                full_response += token
                yield self._format_sse_event(StreamEventType.CHUNK, token)

            # 5. Generate Mesage citations based on utilized chunks 
            yield self._format_sse_event(StreamEventType.STATUS, "Generating citations...", "Citations")

            citations = await self.citation_svc.generate_citations(chunks)
            yield self._format_sse_event(StreamEventType.CITATION, citations)

            # 6. Finalize and Persist
            yield self._format_sse_event(StreamEventType.STATUS, "Finalizing response...", "Finalizing")
            
            user_prompt_tokens, model_output_tokens, total_tokens = await self.calculate_token_totals(message.content, full_response, llm)
            query_result_for_save = QueryResponse(
                user_prompt=message.content,
                model_response=full_response,
                user_input_tokens=user_prompt_tokens,
                model_output_tokens=model_output_tokens,
                total_tokens=total_tokens
            )

            user_msg, model_msg = await self.save_messages(
                query_result_for_save,
                conversation_id,
                message.content_type,
                len(conversation.messages)
            )

            await self.citation_svc.save_citations(citations, model_msg.id)
            await self.conversation_svc.update_total_tokens(conversation_id, total_tokens)

            # manually commit transaction (THIS IS REQUIRED FOR STREAMINGRESPONSE) 
            await self.db.commit() 
            await self.db.refresh(user_msg)
            await self.db.refresh(model_msg)

            # 7. Final Metadata
            yield self._format_sse_event(StreamEventType.METADATA, {
                "user_message": self._get_message_dto(user_msg).model_dump(),
                "model_message": self._get_message_dto(model_msg).model_dump(),
                "conversation_id": str(conversation_id)
            }, "Metadata")

        except Exception as e:
            logger.error(f"Error in streaming message for conversation {conversation_id}: {str(e)}", exc_info=True)
            yield self._format_sse_event(StreamEventType.ERROR, str(e), "Error")
    


    async def calculate_token_totals(self, user_prompt: str, model_output: str, llm: LLMBase) -> tuple[int, int, int]:
        """
        Calculate the token totals for the user prompt and model output.
        """
        user_prompt_tokens = len(await llm.tokenize(user_prompt))
        model_output_tokens = len(await llm.tokenize(model_output))
        total_tokens = user_prompt_tokens + model_output_tokens
        return user_prompt_tokens, model_output_tokens, total_tokens
    
    def _format_sse_event(self, event_type: StreamEventType, data: Any, description: str | None = None) -> str:
        """
        Format a single SSE event string.
        """
        event = StreamEvent(event=event_type, data=data, description=description)
        # follow SSE standard (data: <json>\n\n)
        return f"data: {event.model_dump_json()}\n\n"

    
    def _get_message_dto(self, message: Message) -> MessageDto:
        return MessageDto(
            id=message.id,
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


    

        

        