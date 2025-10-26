from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID


class ProjectRequest(BaseModel):
    name: str
    teams: Optional[List[UUID]] = [] # Note: once Team model is setup, this should likely be enforced
    epics: Optional[List[str]] = [] # List of Jira Epic's, that we can later used to determine if relevant "commits" should be include in collection
