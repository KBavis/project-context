from __future__ import annotations
from app.pydantic.streaming import StreamEvent, StreamEventType
from typing import Any

def get_normalized_project_name(project_name: str):
    """
    Helper function to get normalized project name, which is used when 
    naming our ChromaDb collections 

    Args:
        project_name (str): project name to normalize 
    """
    return "".join(c.upper() for c in project_name if c.isalnum())



    
def format_sse_event(event_type: StreamEventType, data: Any, description: str | None = None) -> str:
    """
    Format a single SSE event string.
    """
    event = StreamEvent(event=event_type, data=data, description=description)
    # follow SSE standard (data: <json>\n\n)
    return f"data: {event.model_dump_json()}\n\n"
