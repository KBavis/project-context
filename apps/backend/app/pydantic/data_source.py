from pydantic import BaseModel
from typing import Optional

class DataSource(BaseModel):
    provider: str 
    url: str
    api_key: Optional[str] = None
    token: Optional[str] = None
