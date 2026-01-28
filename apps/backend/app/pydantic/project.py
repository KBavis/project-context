from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID

from app.core import settings


class ProjectRequest(BaseModel):
    name: str

    # allow for model configuration during project creation
    code_embedding_provider: str = settings.CODE_EMBEDDING_PROVIDER
    code_embedding_model: str = settings.CODE_EMBEDDING_MODEL
    docs_embedding_provider: str = settings.DOCS_EMBEDDING_PROVIDER
    docs_embedding_model: str = settings.DOCS_EMBEDDING_MODEL
    
    lob: Optional[str] = "N/A"
    meta_data: Optional[List[str]] = []
    dependent_projects: Optional[List[UUID]] = []

    teams: Optional[List[UUID]] = (
        []
    )  # Note: once Team model is setup, this should likely be enforced
    epics: Optional[List[str]] = (
        []
    )  # List of Jira Epic's, that we can later used to determine if relevant "commits" should be include in collection
