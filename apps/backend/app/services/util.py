from __future__ import annotations
from app.pydantic.streaming import StreamEvent, StreamEventType
from typing import Any


def format_sse_event(event_type: StreamEventType, data: Any, description: str | None = None) -> str:
    """
    Format a single SSE event string.
    """
    event = StreamEvent(event=event_type, data=data, description=description)
    # follow SSE standard (data: <json>\n\n)
    return f"data: {event.model_dump_json()}\n\n"
