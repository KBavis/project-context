from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.dialects.postgresql import UUID


class Project(BaseModel):
    name: str
    teams: Optional[List[UUID]] = [] # Note: once Team model is setup, this should likely be enforced
    epics: Optional[List[str]] = [] # List of Jira Epic's, that we can later used to determine if relevant "commits" should be include in collection
