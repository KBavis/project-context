
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from uuid import UUID

from app.pydantic import MessageRequest, UpdateConversationRequest
from app.services.message import MessageService
from app.llm import LLMManager
from app.core import settings, get_async_db_session

from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/message")


@router.post("/{conversation_id}", summary="Send a new message to a conversation with LLM regarding a project")
async def send_message(
    message: MessageRequest,
    db: AsyncSession = Depends(get_async_db_session),
):
    """
    Send a new message to a conversation with LLM regarding a project

    Args:
        message (MessageRequest): content of user sent Message
        db (AsyncSession): database session 
    """

    try:    

        message_svc = MessageService(
            db=db
        )
        


        # TODO: Stream LLM response back to user 

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )
