from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING
from sqlalchemy import text
from uuid import UUID

# avoid warning 
if TYPE_CHECKING:
    from .ingestion_job import IngestionJob 
    from .project_data import ProjectData

class DataSource(Base):
    __tablename__ = "data_source"

    id: Mapped[UUID] = mapped_column(primary_key=True, index=True, server_default=text("gen_random_uuid()"))
    provider: Mapped[str] = mapped_column(nullable=False, comment="Specific provider this datasource belongs to (GitHub, BitBucket, Confluence, etc)")
    source_type: Mapped[str] = mapped_column(nullable=False, comment="Type of data this datasource contains (Messages, Documentation, Code)") 

    """Optional fields for provider specific data sources"""
    token: Mapped[str] = mapped_column(nullable=True, comment="Security token for private repositories")
    api_key: Mapped[str] = mapped_column(nullable=True, comment="API Key for private data sources (i.e Confluence for Organization)")
    url: Mapped[str] = mapped_column(nullable=True, comment="URL corresponding to public/private repostiory this data may correspond to")


    # one to many relationship with IngestionJob
    ingestion_jobs: Mapped[List["IngestionJob"]] = relationship(
        back_populates="data_source",
        cascade="all, delete-orphan"
    )

    # many to many relationship with Project 
    project_data: Mapped[List["ProjectData"]] = relationship(back_populates="data_source")
    