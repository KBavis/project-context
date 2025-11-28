from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.pydantic import ChatRequest
from app.core import get_db_session
from app.services import ConversationService



router = APIRouter(prefix="/conversation")


@router.post("/", summary="Start a new conversation with LLM regarding a project")
def create_new_conversation(
    chat: ChatRequest,
    db: Session = Depends(get_db_session)
):
    """
    Start a new conversation with a fresh context with a model regarding a project
    """

    try:
        svc = ConversationService(db)
        return svc.create_conversation(chat)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )


@router.post("/{conversation_id}", summary="Continue existing conversation with LLM regarding a project")
def update_conversation(
    chat: ChatRequest,
    db: Session = Depends(get_db_session)
):
    """
    Continue existing conversation with LLM regarding a particular project
    """
    try:
        svc = ConversationService(db)
        return svc.update_conversation(chat)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )


@router.delete("/{conversation_id}", summary="Delete existing conversation with LLM")
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db_session)
):
    """
    Delete existing conversation with LLM
    """
    try:
        svc = ConversationService(db)
        return svc.delete_conversation(conversation_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )