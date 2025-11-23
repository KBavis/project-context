from pydantic import BaseModel
from uuid import UUID


class FileMetadata(BaseModel):
    path: str
    file_name: str 
    data_source_id: UUID # which data source this file came from
    project_id: UUID # which project this file belongs to  
    size: int # number of bytes in file
