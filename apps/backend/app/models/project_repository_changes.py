from __future__ import annotations

from typing import TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import ARRAY, ForeignKey, ForeignKeyConstraint, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .file_diff import FileDiff
    from .ingestion_job import IngestionJob
    from .project_data import ProjectData
    from .git_commit import GitCommit


class ProjectRepositoryChanges(Base):
    """
    Aggregate project contribution on a single repository DataSource.

    One row per ProjectData link (project_id + data_source_id), when issue-scoped
    diff tracking is enabled for that repository.
    """

    __tablename__ = "project_repository_changes"

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "data_source_id"],
            ["project_data.project_id", "project_data.data_source_id"],
        ),
    )

    base_commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment="SHA of the commit immediately before the project's first commit; "
                "computed once on first sync and reused on subsequent syncs",
    )

    # sync information regarding this state of project repository changes 
    last_synced_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True, comment="End time of IngestionJob processing")

    files_touched: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        insert_default=list,
        comment="Repo-relative paths in the net composition diff (denormalized)",
    )
    file_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="Number of paths in files_touched",
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
    ingestion_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_job.id"),
        index=True,
        nullable=False,
        comment="Last ingestion job that updated this record",
    )

    # one to one relationship with ProjectData
    project_data: Mapped["ProjectData"] = relationship(
        back_populates="repository_changes",
    )

    # many to one with IngestionJob (no reverse collection on IngestionJob)
    ingestion_job: Mapped["IngestionJob"] = relationship()

    # one to many relationship with FileDiff
    file_diffs: Mapped[List["FileDiff"]] = relationship(
        back_populates="project_repository_changes",
        cascade="all, delete-orphan",
    )

    # one to many relationship with GitCommit
    commits: Mapped[List["GitCommit"]] = relationship(
        back_populates="project_repository_changes",
        cascade="all, delete-orphan",
    )
