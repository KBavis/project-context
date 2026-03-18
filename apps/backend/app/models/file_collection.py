from __future__ import annotations
from .base import Base

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, Index

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .file import File
    from .collection import ChromaCollection

class FileCollection(Base):
    """
    Association table for a particular File and the corresponding 
    ChromaCollections that its associated to 

    NOTE: This allows for easy checking of whether or not a particular file has been 
    chunked and stored for a given Chroma collection
    """

    __tablename__: str = "file_collection"

    # ensure data_source is leading column in index, to mitigate blocking of IngestionJobs
    __table_args__ = (
        Index("ix_file_collection_file_id", "file_id"),
        Index("ix_file_collection_chroma_collection_id", "chroma_collection_id"),
    )

    file_id = mapped_column(
        ForeignKey("file.id", ondelete="CASCADE"),
        primary_key=True
    )
    chroma_collection_id = mapped_column(
        ForeignKey("chroma_collection.id"),
        primary_key=True
    )

    file: Mapped["File"] = relationship(
        "File",
        back_populates="file_collections"
    )
    chroma_collection: Mapped["ChromaCollection"] = relationship(
        "ChromaCollection",
        back_populates="file_collections"
    )






