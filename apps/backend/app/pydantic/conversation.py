from pydantic import BaseModel
from uuid import UUID

class UpdateConversationRequest(BaseModel):
    summary: str

class CreateConversationRequest(BaseModel):
    
    project_id: UUID

    # optional LLM model fields (use the configured model if not specified)
    ll_model_name: str | None = None
    ll_model_provider: str | None = None
    
