from __future__ import annotations

from typing import TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKeyConstraint, String, DateTime, Text, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .project_repository_changes import ProjectRepositoryChanges
    from .file_diff import FileDiff


class GitCommit(Base):
    """
    Represents a specific Git commit retrieved from a repository DataSource
    associated with a Project.
    """

    __tablename__ = "git_commit"

    commit_hash: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        comment="Commit SHA-1 hash",
    )

    # Scoped FK back to ProjectRepositoryChanges
    project_id: Mapped[UUID] = mapped_column(
        nullable=False,
        comment="Associated project ID",
    )
    data_source_id: Mapped[UUID] = mapped_column(
        nullable=False,
        comment="Associated repository data source ID",
    )

    author_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Name of the commit author",
    )
    author_email: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Email of the commit author",
    )
    commit_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Date and time when the commit was authored/committed",
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Commit message",
    )
    files_modified: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        insert_default=list,
        comment="Paths modified in this specific commit",
    )

    # Composite foreign key constraint to link to ProjectRepositoryChanges
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "data_source_id"],
            ["project_repository_changes.project_id", "project_repository_changes.data_source_id"],
            ondelete="CASCADE",
        ),
    )

    # Relationships
    project_repository_changes: Mapped["ProjectRepositoryChanges"] = relationship(
        back_populates="commits",
    )

    file_diffs: Mapped[List["FileDiff"]] = relationship(
        secondary="file_diff_commit",
        back_populates="commits",
    )
