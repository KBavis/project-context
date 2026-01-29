from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from uuid import UUID

from app.pydantic import CreateConversationRequest, UpdateConversationRequest
from app.services.conversation import ConversationService
from app.services.query import QueryService
from app.llm import LLMManager
from app.core import settings, get_async_db_session
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.svc_deps import get_async_query_svc

router = APIRouter(prefix="/conversation")


@router.post("/", summary="Start a new conversation with LLM regarding a project")
async def create_new_conversation(
    conversation: CreateConversationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db_session),
    query_svc: QueryService = Depends(get_async_query_svc)
):
    """
    Start a new conversation with a fresh context with a model regarding a project
    """

    try:
        # Create LLMManager based on request parameters (or use defaults)
        llm_manager = LLMManager(
            model_name=conversation.ll_model_name or settings.LL_MODEL,
            provider=conversation.ll_model_provider or settings.LL_MODEL_PROVIDER
        )
        
        # Create service with the configured LLM manager
        svc = ConversationService(db=db, query_svc=query_svc, llm_manager=llm_manager)
        
        created_conversation = await svc.create_conversation(conversation)

        # download and cache embeddings in background
        background_tasks.add_task(query_svc.download_and_cache_embeddings, conversation.project_id)

        return created_conversation
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )


@router.post("/{conversation_id}", summary="Continue existing conversation with LLM regarding a project")
async def update_conversation(
    conversation: UpdateConversationRequest,
    db: AsyncSession = Depends(get_async_db_session),
    query_svc: QueryService = Depends(get_async_query_svc)
):
    """
    Continue existing conversation with LLM regarding a particular project
    """
    try:
        llm_manager = LLMManager()
        svc = ConversationService(db=db, query_svc=query_svc, llm_manager=llm_manager)
        
        updated_conversation = await svc.update_conversation(conversation)
        
        return updated_conversation
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )
        

@router.delete("/{conversation_id}", summary="Delete existing conversation with LLM")
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_async_db_session),
    query_svc: QueryService = Depends(get_async_query_svc)
):
    """
    Delete existing conversation with LLM
    """
    try:
        # Delete doesn't need LLM manager
        llm_manager = LLMManager()
        svc = ConversationService(db=db, query_svc=query_svc, llm_manager=llm_manager)
        
        await svc.delete_conversation(conversation_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )