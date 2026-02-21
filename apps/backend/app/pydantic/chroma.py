from pydantic import BaseModel
from typing import TypedDict, Any
from collections.abc import Sequence
from chromadb.api.types import Metadata, Embeddings, PyEmbeddings

class DeleteCollectionDocsRequest(BaseModel):
    doc_ids: list[str]


# Type definitions for ChromaDB responses
class CollectionFilesResponse(TypedDict, total=False):
    """Response containing actual collection files data"""
    doc_ids: Sequence[str]
    documents: Sequence[str] | None
    meta_datas: Sequence[Metadata] | None
    embeddings: Embeddings | PyEmbeddings | Any | None


class MessageResponse(TypedDict):
    """Response containing a message"""
    message: str


class DeleteCollectionRequest(BaseModel):
    names: list[str]
