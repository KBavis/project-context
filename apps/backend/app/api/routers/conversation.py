from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from uuid import UUID

from app.pydantic import CreateConversationRequest, UpdateConversationRequest
from app.services.conversation import ConversationService

from app.api.svc_deps import get_async_conversation_svc

router = APIRouter(prefix="/conversation")


@router.get("/", summary="Retrieve all conversations")
async def get_conversations(
    conversation_svc: ConversationService = Depends(get_async_conversation_svc)
):
    """
    Retrieve all conversations
    """
    try:
        return await conversation_svc.get_all_conversations()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )


@router.post("/", summary="Start a new conversation with LLM regarding a project")
async def create_new_conversation(
    conversation: CreateConversationRequest,
    background_tasks: BackgroundTasks,
    conversation_svc: ConversationService = Depends(get_async_conversation_svc)
):
    """
    Start a new conversation with a fresh context with a model regarding a project
    """

    try:
        created_conversation = await conversation_svc.create_conversation(conversation)

        # download and cache embeddings in background 
        # TODO: This seems a bit odd, probably a better way to do this 
        background_tasks.add_task(conversation_svc.query_svc.download_and_cache_embeddings, conversation.project_id)

        return created_conversation
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )


@router.post("/{conversation_id}", summary="Continue existing conversation with LLM regarding a project")
async def update_conversation(
    conversation: UpdateConversationRequest,
    conversation_svc: ConversationService = Depends(get_async_conversation_svc)
):
    """
    Continue existing conversation with LLM regarding a particular project
    """
    try:
        updated_conversation = await conversation_svc.update_conversation(conversation)
        
        return updated_conversation
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )
        

@router.delete("/{conversation_id}", summary="Delete existing conversation with LLM")
async def delete_conversation(
    conversation_id: UUID,
    conversation_svc: ConversationService = Depends(get_async_conversation_svc)
):
    """
    Delete existing conversation with LLM
    """
    try:
        await conversation_svc.delete_conversation(conversation_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )