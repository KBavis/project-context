from __future__ import annotations

from llama_index.core.llms import ChatMessage, MessageRole
from app.models import Conversation, Sender

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.pydantic.file import FileCitation
from app.services.conversation import ConversationService
from app.services.agent import AgentService
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
from app.services.util import format_sse_event


logger = logging.getLogger(__name__)

class MessageService:
    def __init__(
        self, 
        db: AsyncSession,
        conversation_svc: ConversationService,
        query_svc: QueryService,
        citation_svc: CitationService,
        agent_svc: AgentService
    ):
        self.db = db
        self.conversation_svc = conversation_svc
        self.query_svc = query_svc
        self.citation_svc = citation_svc
        self.agent_svc = agent_svc

    
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
        conversation_history = self.get_conversation_history(conversation)
        if not conversation_history:
            logger.warning(f"No existing messages found for conversation {conversation_id}")

        # decompose query
        llm = llm_manager.get_llm()
        decomposition_result = await llm.decompose_query(message.content, conversation_history)
        logger.debug(f"Decomposition Result for the Conversation={conversation_id} and Message={message.content}: {decomposition_result}")

        # execute query
        query_result = await self.query_svc.execute_query(
            query=message.content, 
            project_id=conversation.project_id, 
            llm_manager=llm_manager, 
            decomposition=decomposition_result, 
            existing_messages=conversation_history, 
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

    
    async def agentic_send_message_stream(self, message: MessageRequest, conversation_id: UUID) -> AsyncGenerator[str, None]:
        """
        Stream response back to user, providing intermerdiate status updates, and leveraging an Agentic workflow 

        Args:
            message (MessageRequest): users prompt 
            conversation_id (UUID): ID of the conversation to send the message to
        
        Yields:
            str: SSE formatted event with intermediate status updates
        """

        try:
            # 1. Initialize 
            yield format_sse_event(StreamEventType.STATUS, "Initializing conversation context...", "Initializing")
            
            conversation = await self.conversation_svc.get_conversation(conversation_id)
            if not conversation:
                yield format_sse_event(StreamEventType.ERROR, f"Conversation {conversation_id} not found", "Error")
                return

            llm_manager = LLMManager(model_name=conversation.ll_model_name, provider=conversation.ll_model_provider)
            llm = llm_manager.get_llm()



            # 2. Generate Conversation Summary (if needed)
            if conversation.summary is None:
                logger.info(f"Conversation {conversation_id} has no summary, generating one...")
                yield format_sse_event(StreamEventType.STATUS, "Generating conversation summary...", "Summarizing")
                await self.conversation_svc.create_conversation_summary(conversation, message.content, llm_manager)


            # 3. Retrieve Conversation History & Decompose Query If Needed
            conversation_history = self.get_conversation_history_for_agent(conversation)
            if not conversation_history:
                logger.debug(f"No existing messages found for conversation {conversation_id}")


            # 4. Kick of Agentic Flow 
            yield format_sse_event(StreamEventType.STATUS, "Executing Agentic Workflow...", "Executing")
            response_stream = self.agent_svc.run_agent( 
                llm,
                message.content,
                conversation_history,
                conversation.project_id
            )
            
            full_response = ""
            async for sse_event, raw_chunk in response_stream:
                if raw_chunk:
                    full_response += raw_chunk
                yield sse_event

            # 5. Finalize and Persist
            yield format_sse_event(StreamEventType.STATUS, "Finalizing response...", "Finalizing")
            
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

            await self.conversation_svc.update_total_tokens(conversation_id, total_tokens)
            await self.db.commit() 

            # 6. Final Metadata
            yield format_sse_event(StreamEventType.METADATA, {
                "user_message": self._get_message_dto(user_msg).model_dump(),
                "model_message": self._get_message_dto(model_msg).model_dump(),
                "conversation_id": str(conversation_id)
            }, "Metadata")

        except Exception as e:
            logger.error(f"Error in agentic streaming for conversation {conversation_id}: {str(e)}", exc_info=True)
            yield format_sse_event(StreamEventType.ERROR, str(e), "Error")
            




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
            yield format_sse_event(StreamEventType.STATUS, "Initializing conversation context...", "Initializing")
            
            conversation = await self.conversation_svc.get_conversation(conversation_id)
            if not conversation:
                yield format_sse_event(StreamEventType.ERROR, f"Conversation {conversation_id} not found", "Error")
                return

            llm_manager = LLMManager(model_name=conversation.ll_model_name, provider=conversation.ll_model_provider)
            llm = llm_manager.get_llm()

            # 2. Generate Conversation Summary (if needed)
            if conversation.summary is None:
                logger.info(f"Conversation {conversation_id} has no summary, generating one...")
                yield format_sse_event(StreamEventType.STATUS, "Generating conversation summary...", "Summarizing")
                await self.conversation_svc.create_conversation_summary(conversation, message.content, llm_manager)

            # 3. Retrieve Conversation History & Decompose Query If Needed
            conversation_history = self.get_conversation_history(conversation)
            if not conversation_history:
                logger.debug(f"No existing messages found for conversation {conversation_id}")
            
            yield format_sse_event(StreamEventType.STATUS, "Analyzing query and retrieving context...", "Retrieving")
            decomposition_result = await llm.decompose_query(message.content, conversation_history)
            logger.info(f"Decomposition Result for the Conversation={conversation_id}: {decomposition_result}")
            
            # 4. Prompt LLM and retrieve relevant context
            yield format_sse_event(StreamEventType.STATUS, "Generating response...", "Generating")
            logger.info(f"Starting LLM Stream for the Conversation={conversation_id}")

            chunks, llm_response_stream = await self.query_svc.execute_query_stream(
                query=message.content,
                project_id=conversation.project_id,
                llm_manager=llm_manager,
                decomposition=decomposition_result,
                existing_messages=conversation_history,
                existing_tokens=conversation.total_tokens
            )
            full_response = ""
            async for token in llm_response_stream:
                full_response += token
                yield format_sse_event(StreamEventType.CHUNK, token)

            # 5. Generate Mesage citations based on utilized chunks 
            yield format_sse_event(StreamEventType.STATUS, "Generating citations...", "Citations")

            citations = await self.citation_svc.generate_citations(chunks)
            yield format_sse_event(StreamEventType.CITATION, citations)

            # 6. Finalize and Persist
            yield format_sse_event(StreamEventType.STATUS, "Finalizing response...", "Finalizing")
            
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

            # TODO: This is currently incorrect, we currently assume that the conversation total 
            # is = CONVERSATION_TOTAL_TOKEN_HISTORY  + MODEL_OUTPUT_TOKENS + USER_INPUT_TOKENS
            #, but after k number of messages, we filter out older messages 
            # we should account for this so that the conversation total reflects what we are 
            # sending to model
            await self.conversation_svc.update_total_tokens(conversation_id, total_tokens)

            # manually commit transaction (THIS IS REQUIRED FOR STREAMINGRESPONSE) 
            await self.db.commit() 
            await self.db.refresh(user_msg)
            await self.db.refresh(model_msg)

            # 7. Final Metadata
            yield format_sse_event(StreamEventType.METADATA, {
                "user_message": self._get_message_dto(user_msg).model_dump(),
                "model_message": self._get_message_dto(model_msg).model_dump(),
                "conversation_id": str(conversation_id)
            }, "Metadata")

        except Exception as e:
            logger.error(f"Error in streaming message for conversation {conversation_id}: {str(e)}", exc_info=True)
            yield format_sse_event(StreamEventType.ERROR, str(e), "Error")
    


    async def calculate_token_totals(self, user_prompt: str, model_output: str, llm: LLMBase) -> tuple[int, int, int]:
        """
        Calculate the token totals for the user prompt and model output.
        """
        user_prompt_tokens = len(await llm.tokenize(user_prompt))
        model_output_tokens = len(await llm.tokenize(model_output))
        total_tokens = user_prompt_tokens + model_output_tokens
        return user_prompt_tokens, model_output_tokens, total_tokens

    
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

        logger.debug(f"Saved User & Model Messages for Conversation={conversation_id} and User Prompt='{query_result.user_prompt}' and Model Response='{query_result.model_response[:50]}...'")

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
    

    def get_conversation_history_for_agent(self, conversation: Conversation) -> list[ChatMessage]:
        """
        Functionality to retrieve the last k messages for a specific Conversation
        """

        return [ChatMessage(content=msg.content, role=MessageRole.USER if msg.sender == Sender.USER else MessageRole.ASSISTANT) for msg in conversation.messages]
        

    
    def get_conversation_history(self, conversation: Conversation, k: int = 1000) -> str:
        """
        Functionality to retrieve the last k messages for a specific Conversation

        TODO: As of now, we will account for all messages in order to ensure that the token 
        calculations we are performing are working as expected, but we should come back to this 
        and update K to be a fixed number, and if its exceeded, we should leverage 
        the compress_old_messages method to compress the oldest messages into a summary (
        and then account for this in the token total for the conversation)

        TODO: Account for differnet content types 

        Args:
            conversation (Conversation): Conversation to retrieve previous messages for
            k (int): Number of previous messages to retrieve
        """ 

        # ensure messages exist 
        messages = conversation.messages
        if not messages:
            return ""

        # TODO: Complete me!
        # if len(messages) > k:
        #     summary = self.compress_old_messages(messages)

        # retrieve converastion history and filter out older messages 
        # TODO: This is incorrect atm, this should be taking most recent messages instead of oldest 
        # so this should be max heap (or we should just simply sort instead)
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
    

    def compress_old_messages(self, messages: list[Message]) -> str:
        """
        TODO:
            1) Update conversation to have a running history attribute 
            2) Update LLM to have a compress_messages method 
            3) Call this method when the number of messages exceeds our threshold 
            4) Re-evaluate how we are calculating token totals for conversations
        """

        return ""
        
    

        

        