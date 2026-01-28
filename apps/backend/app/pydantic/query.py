from pydantic import BaseModel
from uuid import UUID

class QueryRequest(BaseModel):
    query: str
    project_id: UUID

