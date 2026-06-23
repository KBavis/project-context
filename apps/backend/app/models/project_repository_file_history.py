from __future__ import annotations

from typing import TYPE_CHECKING, List
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    text,
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from app.pydantic.change_type import ChangeType

if TYPE_CHECKING:
    from .diff_sync_job import DiffSyncJob
    from .project_repository_changes import ProjectRepositoryChanges
    from .project_repository_file_pr_diff import ProjectRepositoryFilePrDiff


class ProjectRepositoryFileHistory(Base):
    """
    A single file's change history produced by one project on one repository
    DataSource.
    """

    __tablename__ = "project_repository_file_history"

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "data_source_id"],
            [
                "project_repository_changes.project_id",
                "project_repository_changes.data_source_id",
            ],
            deferrable=True,  # only enforce the constraint at transaction commit
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "project_id",
            "data_source_id",
            "file_path",
            name="uq_project_repository_file_history_path",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        index=True,
        server_default=text("gen_random_uuid()"),
    )

    project_id: Mapped[UUID] = mapped_column(
        index=True,
        nullable=False,
    )
    data_source_id: Mapped[UUID] = mapped_column(
        index=True,
        nullable=False,
    )

    # NOTE: Not a FK to File because we want to retain deleted / moved-path history. 
    # In the future, we may want to re-couple the models and just no longer remove the File row 
    # when the path is deleted, but instead indicate the "availability" of the File (i.e end date)
    file_path: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Repo-relative path; primary identity (no FK to file table)",
    )

    change_type: Mapped[ChangeType] = mapped_column(
        SQLAlchemyEnum(ChangeType, name="change_type_enum"),
        nullable=False,
        comment="Roll-up of the project's net effect on this path: ADDED if the project "
                "created the file, MODIFIED if it pre-existed, DELETED only when the project "
                "removed a pre-existing file. Seeded by the first per-PR diff.",
    )

    diff_sync_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("diff_sync_job.id"),
        index=True,
        nullable=True,
        comment="Job that last wrote this row; used to determine last time this path was synced",
    )

    project_repository_changes: Mapped["ProjectRepositoryChanges"] = relationship(
        back_populates="file_histories",
    )
    diff_sync_job: Mapped["DiffSyncJob"] = relationship()

    pr_diffs: Mapped[List["ProjectRepositoryFilePrDiff"]] = relationship(
        back_populates="file_history",
        cascade="all, delete-orphan",
        order_by="ProjectRepositoryFilePrDiff.ordinal",
    )
