from __future__ import annotations
from .base import Base
from sqlalchemy import text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List
from uuid import UUID

if TYPE_CHECKING:
    from .project import Project
    from .file_collection import FileCollection

class ChromaCollection(Base):

    __tablename__: str = "chroma_collection"

    id: Mapped["UUID"] = mapped_column(
        primary_key=True,
        index=True,
        server_default=text("gen_random_uuid()")
    )

    name: Mapped[str] = mapped_column(
        nullable=False,
        index=True,
        comment="Name of the ChromaCollection"
    )

    embedding_provider: Mapped[str] = mapped_column(
        nullable=False,
        comment="The embedidng provider configured for this ChromaCollection"
    )

    embedding_model: Mapped[str] = mapped_column(
        nullable=False,
        comment="The embedding model configured for this ChromaCollection"
    )

    total_chunks: Mapped[int] = mapped_column(
        nullable=False,
        server_default=text("0"),
        comment="Number of Chunks ingested into this collection"
    )

    total_documents: Mapped[int] = mapped_column(
        nullable=False,
        server_default=text("0"),
        comment="Number of Documents (i.e files) ingested into this collection"
    )

    project_id: Mapped["UUID"] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK to Project that this collection belongs to"
    )

    # many to one relationship with Project
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="chroma_collection"
    )


    # one to many relationship with FileCollection
    file_collections: Mapped[List["FileCollection"]] = relationship(
        "FileCollection",
        back_populates="chroma_collection", 
        cascade="all, delete-orphan"
    )