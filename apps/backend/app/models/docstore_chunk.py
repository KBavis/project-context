from __future__ import annotations
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

class DocstoreChunk(Base):
    """
    Model representing a record within the LlamaIndex Postgres DocStore table.
    """

    __tablename__ = 'data_chunks_docstore'
    __table_args__ = {'extend_existing': True}

    key: Mapped[str] = mapped_column(String, primary_key=True)
    namespace: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)

    @property
    def node_text(self) -> str | None:
        """Helper to access nested text content"""
        data = self.value.get("__data__", self.value)
        return data.get("text")

    @property
    def node_metadata(self) -> dict:
        """Helper to access nested metadata"""
        data = self.value.get("__data__", self.value)
        return data.get("metadata", {})
