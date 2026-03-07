from pydantic import BaseModel
from typing import List


class DataSourceRequest(BaseModel):
    provider: str
    url: str
    name: str
    branch: str | None = None
    project_ids: List[str] = []  # list of Jira Epics corresponding to this DataSource
