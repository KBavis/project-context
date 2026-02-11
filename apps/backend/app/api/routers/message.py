
from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID

from app.pydantic import MessageRequest
from app.services.message import MessageService
from app.api.svc_deps import get_async_message_svc

router = APIRouter(prefix="/message")


@router.post("/{conversation_id}", summary="Send a new message to a conversation with LLM regarding a project")
async def send_message(
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
        message = await message_svc.send_message(message, conversation_id)
        return message

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )
