from __future__ import annotations
from .base import Base
from typing import TYPE_CHECKING
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import ForeignKey
from uuid import UUID

if TYPE_CHECKING:
    from .data_source import DataSource
    from .project import Project
    from .project_repo_summary import ProjectRepoSummary


class ProjectData(Base):
    __tablename__: str = "project_data"

    project_id: Mapped["UUID"] = mapped_column(ForeignKey("project.id"), primary_key=True)
    data_source_id: Mapped["UUID"] = mapped_column(
        ForeignKey("data_source.id"), primary_key=True
    )

    # many to many relationship between Project and DataSource
    project: Mapped["Project"] = relationship(back_populates="project_data")
    data_source: Mapped["DataSource"] = relationship(back_populates="project_data")

    # one to one relationship with ProjectRepoSummary (when DataSource.scope_by_issues == TRUE and DataSource.type == REPOSITORY)
    repository_changes: Mapped["ProjectRepoSummary | None"] = relationship(
        back_populates="project_data",
        uselist=False,
    )
