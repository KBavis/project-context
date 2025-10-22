from pydantic import BaseModel

class Chat(BaseModel):
    content: str 
    project_id: int 
    
