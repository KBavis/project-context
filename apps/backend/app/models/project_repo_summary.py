from __future__ import annotations

from typing import TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .project_affected_file import ProjectAffectedFile
    from .diff_task import DiffTask
    from .project_data import ProjectData
    from .pull_request import PullRequest


class ProjectRepoSummary(Base):
    """
    Aggregate project contribution on a single repository DataSource.

    One row per ProjectData link (project_id + data_source_id), when issue-scoped
    diff tracking is enabled for that repository.
    """

    __tablename__ = "project_repo_summary"

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "data_source_id"],
            ["project_data.project_id", "project_data.data_source_id"],
        ),
    )



    last_synced_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True, comment="End time of DiffTask processing")

    file_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="Number of touched files",
    )

    # foreign keys
    project_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        comment="Part of 1:1 PK with ProjectData",
    )
    data_source_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        comment="Part of 1:1 PK with ProjectData",
    )
    last_diff_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("diff_task.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        comment="Last diff sync job that updated this record",
    )

    # one to one relationship with ProjectData
    project_data: Mapped["ProjectData"] = relationship(
        back_populates="repository_changes",
    )

    # many to one with DiffTask (no reverse collection on DiffTask)
    diff_task: Mapped["DiffTask"] = relationship()

    # one to many relationship with ProjectAffectedFile
    file_histories: Mapped[List["ProjectAffectedFile"]] = relationship(
        back_populates="project_repo_summary",
        cascade="all, delete-orphan",
    )

    # one to many relationship with PullRequest
    pull_requests: Mapped[List["PullRequest"]] = relationship(
        back_populates="project_repo_summary",
        cascade="all, delete-orphan",
    )
