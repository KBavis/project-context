from __future__ import annotations
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional

from app.pydantic.status import ProcessingStatus



class JobResponse(BaseModel):
    """Response model for a single Job."""
    id: UUID
    project_id: UUID
    data_source_id: UUID
    status: ProcessingStatus
    start_time: datetime
    end_time: Optional[datetime]
    total_duration: Optional[int]

    class Config:
        from_attributes = True


class LatestJobsByDataSourceResponse(BaseModel):
    """Response model for latest jobs grouped by data source."""
    data_source_id: UUID
    data_source_name: Optional[str] = None
    jobs: list[JobResponse]
