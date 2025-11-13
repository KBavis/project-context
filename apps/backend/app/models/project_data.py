from .base import Base
from typing import TYPE_CHECKING
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import ForeignKey
from uuid import UUID

if TYPE_CHECKING:
    from .data_source import DataSource
    from .project import Project


class ProjectData(Base):
    __tablename__ = "project_data"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id"), primary_key=True)
    data_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_source.id"), primary_key=True
    )

    # many to many relationship between Project and DataSource
    project: Mapped["Project"] = relationship(back_populates="project_data")
    data_source: Mapped["DataSource"] = relationship(back_populates="project_data")
