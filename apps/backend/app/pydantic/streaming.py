from pydantic import BaseModel
from typing import Any, Optional
from enum import Enum

class StreamEventType(str, Enum):
    STATUS = "status"
    CHUNK = "chunk"
    METADATA = "metadata"
    ERROR = "error"
    CITATION = "citation"

class StreamEvent(BaseModel):
    event: StreamEventType
    data: Any
    description: Optional[str] = None
