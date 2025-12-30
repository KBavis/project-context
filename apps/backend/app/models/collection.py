from .base import Base
from sqlalchemy import text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from .project import Project

class ChromaCollection(Base):

    __tablename__ = "chroma_collection"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        index=True,
        server_default=text("gen_random_uuid()")
    )

    name: Mapped[str] = mapped_column(
        nullable=False,
        index=True,
        comment="Name of the ChromaCollection"
    )

    content_type: Mapped[str] = mapped_column(
        nullable=False,
        comment="Type of collection (i.e code, docs, etc)"
    )

    embedding_provider: Mapped[str] = mapped_column(
        nullable=False,
        comment="The embedidng provider configured for this ChromaCollection"
    )

    embedding_model: Mapped[str] = mapped_column(
        nullable=False,
        comment="The embedding model configured for this ChromaCollection"
    )

    doc_count: Mapped[int] = mapped_column(
        nullable=False,
        server_default=0,
        comment="Number of Documents ingested into this collection"
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK to Project that this collection belongs to"
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="chroma_collections"
    )