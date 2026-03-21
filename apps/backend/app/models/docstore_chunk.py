from __future__ import annotations
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class DocstoreBase(DeclarativeBase):
    """Simple base for external tables that don't have our audit columns"""
    pass

class DocstoreChunk(DocstoreBase):
    """
    Model representing a record within the LlamaIndex Postgres DocStore table.
    """

    __tablename__ = 'data_chunks_docstore'
    __table_args__ = {'extend_existing': True}

    key: Mapped[str] = mapped_column(String, primary_key=True)
    namespace: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)

    @property
    def text(self) -> str | None:
        """Helper to access nested text content"""
        return self.value.get("__data__", {}).get("text")

    @property
    def metadata(self) -> dict:
        """Helper to access nested metadata"""
        return self.value.get("__data__", {}).get("metadata", {})
