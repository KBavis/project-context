from __future__ import annotations
from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING
from sqlalchemy import text, ForeignKey, Enum as SQLEnum
from uuid import UUID
from enum import Enum

# avoid warning
if TYPE_CHECKING:
    from .ingestion_job import IngestionJob
    from .project_data import ProjectData
    from .file import File
    from .mcp_config import MCPConfig
    from .data_source_mcp import DataSourceMCPConfig


class DataSourceType(str, Enum):
    REPOSITORY = "REPOSITORY"
    DOCUMENTATION = "DOCUMENTATION"


class DataSource(Base):
    __tablename__: str = "data_source"

    id: Mapped["UUID"] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )
    provider: Mapped[str] = mapped_column(
        nullable=False,
        comment="Specific provider this datasource belongs to (GitHub, BitBucket, Confluence, etc)",
    )
    url: Mapped[str] = mapped_column(
        nullable=False,
        comment="URL corresponding to public/private repostiory this data may correspond to",
    )
    name: Mapped[str] = mapped_column(
        nullable=False,
        comment="Name of the data source",
    )

    branch: Mapped[str] = mapped_column(
        nullable=True,
        comment="Branch of the data source (i.e main, master, etc) if one is applicable",
    )

    type: Mapped["DataSourceType"] = mapped_column(
        SQLEnum(DataSourceType),
        nullable=False,
        comment="Type of data source",
    )


    # many to many relationship with MCPConfig
    data_source_mcp_configs: Mapped[List["DataSourceMCPConfig"]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    ) 

    # one to many relationship with IngestionJob
    ingestion_jobs: Mapped[List["IngestionJob"]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    )

    # many to many relationship with Project
    project_data: Mapped[List["ProjectData"]] = relationship(
        back_populates="data_source"
    )

    # one to many relationship with File 
    files: Mapped[List["File"]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    )
