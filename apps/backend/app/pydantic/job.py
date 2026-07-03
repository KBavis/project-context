from __future__ import annotations
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional

from app.pydantic.status import ProcessingStatus



class DiffTaskResponse(BaseModel):
    id: UUID
    status: ProcessingStatus
    start_time: datetime
    end_time: Optional[datetime]
    total_duration: Optional[int]
    reason: Optional[str] = None

    class Config:
        from_attributes = True

class EmbedTaskResponse(BaseModel):
    id: UUID
    processing_status: ProcessingStatus
    start_time: datetime
    end_time: Optional[datetime]
    total_duration: Optional[int]
    reason: Optional[str] = None

    class Config:
        from_attributes = True

class JobResponse(BaseModel):
    """Response model for a single Job."""
    id: UUID
    project_id: UUID
    data_source_id: UUID
    status: ProcessingStatus
    start_time: datetime
    end_time: Optional[datetime]
    total_duration: Optional[int]
    diff_tasks: list["DiffTaskResponse"] = []
    embed_tasks: list["EmbedTaskResponse"] = []

    class Config:
        from_attributes = True
