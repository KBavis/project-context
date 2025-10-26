from pydantic import BaseModel
from typing import Optional, List

class DataSourceRequest(BaseModel):
    provider: str 
    source_type: str
    url: str
    api_key: Optional[str] = None
    token: Optional[str] = None
    project_ids: List[str] = []
