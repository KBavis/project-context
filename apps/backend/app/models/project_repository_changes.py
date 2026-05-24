from __future__ import annotations

from typing import TYPE_CHECKING, List
from uuid import UUID

from sqlalchemy import ARRAY, ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .file_diff import FileDiff
    from .ingestion_job import IngestionJob
    from .project_data import ProjectData


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

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_data.project_id"),
        primary_key=True,
        comment="Part of 1:1 PK with ProjectData",
    )
    data_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_data.data_source_id"),
        primary_key=True,
        comment="Part of 1:1 PK with ProjectData",
    )

    commit_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        insert_default=list,
        comment="Ordered SHAs attributed to this project on this repository",
    )
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

    ingestion_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_job.id"),
        index=True,
        nullable=False,
        comment="Last ingestion job that updated this row (last_synced_at = job.end_time)",
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
