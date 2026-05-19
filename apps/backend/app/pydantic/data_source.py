from __future__ import annotations
from pydantic import BaseModel
from typing import List
from uuid import UUID
from app.models.data_source import DataSourceType

class DataSourceRequest(BaseModel):
    provider: str
    url: str
    name: str
    type: DataSourceType
    branch: str | None = None
    project_ids: List[UUID] = []  # list of project Ids to associate this DataSource to 
