from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID

from app.pydantic import CreateConversationRequest, UpdateConversationRequest
from app.services import ConversationService
from ..svc_deps import get_conversation_svc



router = APIRouter(prefix="/conversation")


@router.post("/", summary="Start a new conversation with LLM regarding a project")
def create_new_conversation(
    conversation: CreateConversationRequest,
    svc: ConversationService = Depends(get_conversation_svc)
):
    """
    Start a new conversation with a fresh context with a model regarding a project
    """

    try:
        return svc.create_conversation(conversation)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )


@router.post("/{conversation_id}", summary="Continue existing conversation with LLM regarding a project")
def update_conversation(
    conversation: UpdateConversationRequest,
    svc: ConversationService = Depends(get_conversation_svc)
):
    """
    Continue existing conversation with LLM regarding a particular project
    """
    try:
        return svc.update_conversation(conversation)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )


@router.delete("/{conversation_id}", summary="Delete existing conversation with LLM")
def delete_conversation(
    conversation_id: UUID,
    svc: ConversationService = Depends(get_conversation_svc)
):
    """
    Delete existing conversation with LLM
    """
    try:
        return svc.delete_conversation(conversation_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )