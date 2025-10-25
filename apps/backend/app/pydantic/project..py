from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.dialects.postgresql import UUID


class Project(BaseModel):
    name: str
    teams: Optional[List[UUID]] = [] # Note: once Team model is setup, this should likely be enforced
