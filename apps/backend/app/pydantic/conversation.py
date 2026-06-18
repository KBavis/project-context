from __future__ import annotations
from pydantic import BaseModel
from uuid import UUID

from app.core import settings

class UpdateConversationRequest(BaseModel):
    summary: str

class CreateConversationRequest(BaseModel):
    
    project_id: UUID

    # default to use configured LL model (set in service layer)
    ll_model_name: str | None = None
    ll_model_provider: str | None = None