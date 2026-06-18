from __future__ import annotations
from pydantic import BaseModel, model_validator
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
    scope_by_issues: bool = False

    @model_validator(mode="after")
    def validate_repository_fields(self):
        if self.type != DataSourceType.REPOSITORY:
            if self.branch:
                raise ValueError("Branch can only be specified for REPOSITORY data sources.")
            if self.scope_by_issues:
                raise ValueError("scope_by_issues can only be enabled for REPOSITORY data sources.")
        return self


class DataSourceUpdateRequest(BaseModel):
    name: str | None = None
    branch: str | None = None
    scope_by_issues: bool | None = None
    type: DataSourceType | None = None
    url: str | None = None
    provider: str | None = None
