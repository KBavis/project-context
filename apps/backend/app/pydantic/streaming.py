from __future__ import annotations
from pydantic import BaseModel
from typing import Any, Optional
from enum import Enum

class StreamEventType(str, Enum):
    STATUS = "status"
    CHUNK = "chunk"
    METADATA = "metadata"
    ERROR = "error"
    TOKEN_USAGE = "token_usage"

class StreamEvent(BaseModel):
    event: StreamEventType
    data: Any
    description: Optional[str] = None
