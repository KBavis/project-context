from __future__ import annotations
from uuid import UUID
import asyncio
import json
import logging
import heapq
from typing import AsyncGenerator

from llama_index.core.llms import ChatMessage, MessageRole

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from fastapi import HTTPException

from app.models import Conversation, Sender
from app.services.conversation import ConversationService
from app.services.agent import AgentService
from app.services.project import ProjectService
from app.services.execution_token_usage import ExecutionTokenUsageService
from app.models import Message
from app.llm import LLMManager, LLMBase
from app.pydantic import QueryResponse, MessageDto, MessageRequest
from app.pydantic.streaming import StreamEventType
from app.services.util import format_sse_event


logger = logging.getLogger(__name__)

class MessageService:
    def __init__(
        self, 
        db: AsyncSession,
        conversation_svc: ConversationService,
        agent_svc: AgentService,
        execution_token_usage_svc: ExecutionTokenUsageService,
        project_svc: ProjectService,
    ):
        self.db = db
        self.conversation_svc = conversation_svc
        self.agent_svc = agent_svc
        self.execution_token_usage_svc = execution_token_usage_svc
        self.project_svc = project_svc

    
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
            import time
            start_time = time.perf_counter()
            yield format_sse_event(StreamEventType.STATUS, "Initializing conversation context...", "Initializing")
            
            conversation = await self.conversation_svc.get_conversation(conversation_id)
            if not conversation:
                yield format_sse_event(StreamEventType.ERROR, f"Conversation {conversation_id} not found", "Error")
                return

            # 1a. Validate Project's linked "ingestible" DataSources have at least one successful Ingestion Job
            await self.project_svc.validate_project_ready(conversation.project_id)

            llm_manager = LLMManager(model_name=conversation.ll_model_name, provider=conversation.ll_model_provider)
            llm = llm_manager.get_llm()


            # 2. Kick off Conversation Summary generation (if needed) CONCURRENTLY.
            #    We only run the LLM call here (no DB writes) so it can overlap with the
            #    agentic workflow without touching the shared session; it is persisted at commit time.
            summary_task: asyncio.Task | None = None
            if conversation.summary is None:
                logger.info(f"Conversation {conversation_id} has no summary, generating one in the background...")
                summary_task = asyncio.create_task(
                    self.conversation_svc.generate_summary_text(
                        conversation.project.project_name, message.content, llm_manager
                    )
                )


            # 3. Retrieve Conversation History & Decompose Query If Needed
            conversation_history = self.get_conversation_history_for_agent(conversation)
            if not conversation_history:
                logger.debug(f"No existing messages found for conversation {conversation_id}")


            # 4. Kick of Agentic Flow 
            yield format_sse_event(StreamEventType.STATUS, "Executing Agentic Workflow...", "Executing")

            # Fetch the Project so the agent knows *which* project it is assisting with
            project = await self.project_svc.aget_project_by_id(conversation.project_id)

            response_stream = self.agent_svc.run_agent( 
                llm,
                message.content,
                conversation_history,
                conversation.project_id,
                project=project,
            )
            
            full_response = ""
            usage_data = {}
            citations_map: dict = {}
            has_error = False
            async for sse_event, raw_chunk in response_stream:
                # extract usage data regarding tokens 
                if sse_event == StreamEventType.TOKEN_USAGE and isinstance(raw_chunk, dict):
                    usage_data = raw_chunk
                    continue

                # capture + forward the deterministic citation map (used inline + in the footer)
                if sse_event == StreamEventType.CITATIONS and isinstance(raw_chunk, dict):
                    citations_map = raw_chunk
                    yield format_sse_event(StreamEventType.CITATIONS, raw_chunk, "Citations")
                    continue
                
                if isinstance(raw_chunk, str):
                    full_response += raw_chunk
                
                # Only yield if it's a string (SSE event)
                if isinstance(sse_event, str) and sse_event != StreamEventType.TOKEN_USAGE:
                    yield sse_event
                    # Check if the event is an error event by looking for the StreamEventType.ERROR value
                    if f'"event":"{StreamEventType.ERROR.value}"' in sse_event.replace(" ", ""):
                        has_error = True

            # 5. Finalize and Persist
            if not has_error:
                yield format_sse_event(StreamEventType.STATUS, "Finalizing response...", "Finalizing")
            

            # 6. Determine Token Usage via Agentic Workflow (i.e. Execution Cost Metrics)
            agent_workflow_input_tokens = usage_data.get("input_tokens", 0)
            agent_workflow_output_tokens = usage_data.get("output_tokens", 0)
            agent_workflow_total_tokens = usage_data.get("total_tokens", 0)
            logger.info(f"Token Usage for Conversation={conversation_id} and Message={message.content}: {usage_data}")

            # 7. Determine User Input and Model Output Token Totals (actual message content)
            user_prompt_tokens, model_output_tokens, total_tokens = await self.calculate_token_totals(message.content, full_response, llm)

            # 7b. Embed the citation map in the persisted content (as a stripped HTML comment)
            #     so inline cite:<id> links + the grouped footer still render on reload,
            #     without requiring a new DB column. The frontend parses and strips it.
            if citations_map:
                full_response = f"{full_response}\n\n<!--CITATIONS:{json.dumps(citations_map)}-->"

            # 8. Persist Updates (Messages and Conversation Metadata)
            query_result_for_save = QueryResponse(
                user_prompt=message.content,
                model_response=full_response,
                input_tokens=user_prompt_tokens,
                output_tokens=model_output_tokens,
                total_tokens=total_tokens
            )
            user_msg, model_msg = await self.save_messages(
                query_result_for_save,
                conversation_id,
                message.content_type,
                len(conversation.messages)
            )

            await self.conversation_svc.update_total_tokens(conversation_id, total_tokens)
            
            # 9. Persist execution stats
            execution_time_seconds = time.perf_counter() - start_time
            await self.execution_token_usage_svc.create_usage_record(
                conversation_id=conversation_id,
                user_message_id=user_msg.id,
                model_message_id=model_msg.id,
                input_tokens=agent_workflow_input_tokens,
                output_tokens=agent_workflow_output_tokens,
                total_tokens=agent_workflow_total_tokens,
                execution_time_seconds=execution_time_seconds
            )
            await self.conversation_svc.update_total_execution_tokens(conversation_id, agent_workflow_total_tokens)

            # 9b. Persist the concurrently-generated conversation summary (if any).
            if summary_task is not None:
                try:
                    summary_text = await summary_task
                    if summary_text:
                        conversation.summary = summary_text
                        self.db.add(conversation)
                except Exception as summary_err:
                    logger.warning(f"Failed to generate conversation summary for {conversation_id}: {summary_err}")

            await self.db.commit() 


            # 10. Final Metadata
            yield format_sse_event(StreamEventType.METADATA, {
                "user_message": self._get_message_dto(user_msg).model_dump(),
                "model_message": self._get_message_dto(model_msg).model_dump(),
                "conversation_id": str(conversation_id),
                "conversation_summary": conversation.summary,
                "execution_time_seconds": execution_time_seconds
            }, "Metadata")

        except HTTPException as e:
            yield format_sse_event(StreamEventType.ERROR, e.detail, "Error")
        except Exception as e:
            logger.error(f"Error in agentic streaming for conversation {conversation_id}: {str(e)}", exc_info=True)
            yield format_sse_event(StreamEventType.ERROR, str(e), "Error")
            
    
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

    

    async def calculate_token_totals(self, user_prompt: str, model_output: str, llm: LLMBase) -> tuple[int, int, int]:
        """
        Calculate the token totals for the user prompt and model output.
        """
        user_prompt_tokens = len(await llm.tokenize(user_prompt))
        model_output_tokens = len(await llm.tokenize(model_output))
        total_tokens = user_prompt_tokens + model_output_tokens
        return user_prompt_tokens, model_output_tokens, total_tokens

        
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
            token_count=query_result.input_tokens,
            conversation_id=conversation_id
        )
        model_msg = await self.save_message(
            message=query_result.model_response,
            sender=Sender.MODEL,
            sequence_number=model_sequence_number,
            content_type="text", # TODO: Use enum and account for potential types 
            token_count=query_result.output_tokens,
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

        TODO: This is a fairly simplified version this function, in the long run, we should 
        likely look to summarize old messages in order to avoid excessive token usage 
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
        
    

        

        