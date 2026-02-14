
from pydantic import BaseModel


class MessageRequest(BaseModel):
    content: str
    content_type: str = "text"
    