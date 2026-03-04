from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from uuid import UUID

from app.pydantic import MessageRequest, PromptResponse, MessageDto
from app.services.message import MessageService
from app.api.svc_deps import get_async_message_svc

router = APIRouter(prefix="/message")


@router.post("/{conversation_id}", summary="Send a new message to a conversation with LLM regarding a project")
async def send_message_sync(
    conversation_id: UUID,
    message: MessageRequest,
    message_svc: MessageService = Depends(get_async_message_svc)
):
    """
    Send a new message to a conversation with LLM regarding a project

    Args:
        message (MessageRequest): content of user sent Message
        db (AsyncSession): database session 
    """

    try: 
        response: PromptResponse = await message_svc.sync_send_message(message, conversation_id)
        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )
    
@router.post("/{conversation_id}/stream", summary="Send a new message to a conversation and stream the response back via SSE")
async def send_message_stream(
    conversation_id: UUID,
    message: MessageRequest,
    message_svc: MessageService = Depends(get_async_message_svc)
):
    """
    Send a new message to a conversation and stream the response back via SSE.
    """
    return StreamingResponse(
        message_svc.send_message_stream(message, conversation_id),
        media_type="text/event-stream"
    )


@router.get("/{conversation_id}", response_model=list[MessageDto], summary="Get all messages for a conversation")
async def get_messages(
    conversation_id: UUID,
    message_svc: MessageService = Depends(get_async_message_svc)
):
    """
    Get all messages for a conversation

    Args:
        conversation_id (UUID): ID of the conversation to get messages for
        message_svc (MessageService): Message service
    """

    try: 
        messages = await message_svc.get_messages(conversation_id)
        return messages

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )