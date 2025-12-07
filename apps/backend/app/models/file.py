from .base import Base

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import text, ForeignKey, String, Index

from typing import TYPE_CHECKING, List

from uuid import UUID


if TYPE_CHECKING:
    from .data_source import DataSource
    from .file_collection import FileCollection

class File(Base):

    __tablename__ = "file"

    # ensure data_source is leading column in index, to mitigate blocking of IngestionJobs
    __table_args__ = (
        Index("ix_file_data_source_path", "data_source_id", "path"),
        Index("ix_file_data_source_name", "data_source_id", "name"),
        Index("ix_file_data_source_hash", "data_source_id", "hash"),
        Index("ix_file_data_source_fk", "data_source_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )

    hash: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="The hashed file content corresponding to the file"
    )

    size: Mapped[int] = mapped_column(
        nullable=False,
        comment="The number of bytes within this file"
    )

    file_extension: Mapped[str] = mapped_column(
        nullable=False,
        comment="The file extension of this particular file"
    )

    name: Mapped[str] = mapped_column(
        nullable=False,
        comment="The name of the file"
    )

    path: Mapped[str] = mapped_column(
        nullable=True,
        comment="The entire path to the file"
    )

    # one to one relationship with IngestionJob 
    last_ingestion_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_job.id")
    )
    
    # many to one relationship with DataSource
    data_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_source.id")
    )
    data_source: Mapped["DataSource"] = relationship(
        back_populates="files"
    )

    # one to many relationship with FileCollection
    file_collections: Mapped[List["FileCollection"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )