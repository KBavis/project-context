from .base import Base

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import text, ForeignKey, String

from uuid import UUID

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .file import File
    from .project import Project

class FileCollection(Base):
    """
    Association table for a particular File and which Projects currently 
    have it chunked & stored within their relevant collections

    NOTE: This allows for easy checking of whether or not a particular file has been 
    chunked and stored for a given Chroma collection
    """

    __tablename__ = "file_collection"

    file_id = mapped_column(
        ForeignKey("file.id", ondelete="CASCADE"),
        primary_key=True
    )
    project_id = mapped_column(
        ForeignKey("project.id"),
        primary_key=True
    )

    file: Mapped["File"] = relationship(
        "File",
        back_populates="file_collections"
    )
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="file_collections"
    )






