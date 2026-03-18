from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel
from uuid import UUID


class MessageRequest(BaseModel):
    content: str
    content_type: str = "text"


class MessageDto(BaseModel):
    id: UUID
    content: str
    content_type: str
    token_count: int
    sequence_number: int
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel): 
    
    user_message: MessageDto 
    model_message: MessageDto 
    conversation_id: UUID

    