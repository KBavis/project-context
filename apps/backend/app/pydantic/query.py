from __future__ import annotations
from pydantic import BaseModel
from uuid import UUID

class QueryRequest(BaseModel):
    query: str
    project_id: UUID

class QueryResponse(BaseModel):
    user_prompt: str 
    model_response: str 

    user_input_tokens: int 
    model_output_tokens: int 
    total_tokens: int 