from pydantic import BaseModel
from uuid import UUID


class File(BaseModel):
    path: str
    file_name: str 
    content_type: str
    data_source_id: UUID 
    size: int # number of bytes in file
    hash: str # hash based on file content 
