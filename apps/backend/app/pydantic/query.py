from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str
    project_id: str

