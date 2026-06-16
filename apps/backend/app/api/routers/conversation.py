from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from uuid import UUID

from app.pydantic import CreateConversationRequest, UpdateConversationRequest
from app.services.conversation import ConversationService
from app.services.chroma import ChromaService

from app.api.svc_deps import get_async_conversation_svc, get_chroma_svc, get_data_source_svc
from app.services.data_source import DataSourceService

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
    conversation_svc: ConversationService = Depends(get_async_conversation_svc),
    chroma_svc: ChromaService = Depends(get_chroma_svc),
    data_source_svc: DataSourceService = Depends(get_data_source_svc),
):
    """
    Start a new conversation with a fresh context with a model regarding a project
    """

    try:
        created_conversation = await conversation_svc.create_conversation(conversation)

        # download and cache embeddings in background for all data sources
        # associated with this project (we must pass data_source IDs).
        data_sources = await data_source_svc.aget_project_data_sources(conversation.project_id)
        for ds in data_sources:
            background_tasks.add_task(chroma_svc.download_and_cache_collection_embeddings, ds.id)

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