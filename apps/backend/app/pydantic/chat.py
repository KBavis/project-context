from pydantic import BaseModel


class ChatRequest(BaseModel):
    content: str
    project_id: int
