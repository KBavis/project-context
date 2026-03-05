from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID

from app.api.svc_deps import get_async_citation_svc
from app.pydantic import CitationDto
from app.services.citations import CitationService

router = APIRouter(prefix="/citation")

@router.get("/{conversation_id}", response_model=list[CitationDto], summary="Get all citations for a conversation")
async def get_citations(
    conversation_id: UUID,
    citation_svc: CitationService = Depends(get_async_citation_svc)
):
    try:
        citations = await citation_svc.get_citations(conversation_id)
        return citations
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}"
        )