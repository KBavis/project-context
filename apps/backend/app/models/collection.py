from __future__ import annotations
from .base import Base
from sqlalchemy import text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List
from uuid import UUID

if TYPE_CHECKING:
    from .data_source import DataSource

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

    data_source_id: Mapped["UUID"] = mapped_column(
        ForeignKey("data_source.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK to DataSource that this collection belongs to",
        unique=True
    )

    # one to one relationship with DataSource
    data_source: Mapped["DataSource"] = relationship(
        "DataSource",
        back_populates="chroma_collection"
    )
