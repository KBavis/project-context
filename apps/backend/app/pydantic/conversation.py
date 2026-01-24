from pydantic import BaseModel
from uuid import UUID

from app.core import settings

class UpdateConversationRequest(BaseModel):
    summary: str

class CreateConversationRequest(BaseModel):
    
    project_id: UUID

    # default to use configured LL model
    ll_model_name: str = settings.LL_MODEL
    ll_model_provider: str = settings.LL_MODEL_PROVIDER
    
