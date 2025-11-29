from pydantic import BaseModel
from typing import List

class DeleteCollectionDocsRequest(BaseModel):
    doc_ids: List