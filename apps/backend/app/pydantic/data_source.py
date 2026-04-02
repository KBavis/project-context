from __future__ import annotations
from pydantic import BaseModel
from typing import List
from uuid import UUID

class DataSourceRequest(BaseModel):
    provider: str
    url: str
    name: str
    branch: str | None = None
    project_ids: List[UUID] = []  # list of project Ids to associate this DataSource to 
