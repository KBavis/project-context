from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, List
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
    Enum as SQLAlchemyEnum,
    Table,
    Column,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .diff_sync_job import DiffSyncJob
    from .project_repository_changes import ProjectRepositoryChanges
    from .git_commit import GitCommit


class ChangeType(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    UNKNOWN = "unknown"


file_diff_commit = Table(
    "file_diff_commit",
    Base.metadata,
    Column("file_diff_id", SQLAlchemyUUID(as_uuid=True), ForeignKey("file_diff.id", ondelete="CASCADE"), primary_key=True),
    Column("commit_hash", String, ForeignKey("git_commit.commit_hash", ondelete="CASCADE"), primary_key=True),
)


class FileDiff(Base):
    """
    Per-file net composition diff for a project on one repository DataSource.
    """

    __tablename__ = "file_diff"

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
            name="uq_file_diff_project_repository_path",
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
        comment="added | modified | deleted — deleted rows are kept until net-zero reconcile",
    )

    unified_diff: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Git unified diff for this path only (headers + all hunks); not a single hunk or full file",
    )
    diff_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="sha256 hex of bytes stored in unified_diff (after cap); used to skip re-embed",
    )
    diff_truncated: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="True if unified_diff was capped)",
    )

    conflict_detected: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True if at least one cherry-pick SHA could not be applied cleanly; unified_diff may be partial or None",
    )
    failed_commit_shas: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        insert_default=list,
        comment="SHAs that could not be cherry-picked for this file; populated when conflict_detected=True",
    )

    diff_sync_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("diff_sync_job.id"),
        index=True,
        nullable=True,
        comment="Job that last wrote this row; used to determine last time this path was synced",
    )

    project_repository_changes: Mapped["ProjectRepositoryChanges"] = relationship(
        back_populates="file_diffs",
    )
    diff_sync_job: Mapped["DiffSyncJob"] = relationship()

    commits: Mapped[List["GitCommit"]] = relationship(
        secondary="file_diff_commit",
        back_populates="file_diffs",
    )
