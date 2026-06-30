from __future__ import annotations

from typing import TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import (
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    DateTime,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .project_repo_summary import ProjectRepoSummary
    from .project_file_diff import ProjectFileDiff
    from .git_commit import GitCommit


class PullRequest(Base):
    """
    A merged pull request that contributed changes to a project's repository.

    A pull request maps one-to-one to a single child issue (its source branch
    references that issue's key) and is the record that ties project repository
    changes back to the work that introduced them; commits are persisted only as
    descriptive metadata. Only MERGED pull requests are recorded; the per-file
    diffs a PR introduced live in ``ProjectFileDiff`` rows that
    reference this PR.
    """

    __tablename__ = "pull_request"

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "data_source_id"],
            [
                "project_repo_summary.project_id",
                "project_repo_summary.data_source_id",
            ],
            ondelete="CASCADE",
            deferrable=True,  # only enforce the constraint at transaction commit
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "project_id",
            "data_source_id",
            "pr_number",
            name="uq_pull_request_project_repository_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        index=True,
        server_default=text("gen_random_uuid()"),
    )

    # Scoped FK back to ProjectRepoSummary
    project_id: Mapped[UUID] = mapped_column(
        index=True,
        nullable=False,
        comment="Associated project ID",
    )
    data_source_id: Mapped[UUID] = mapped_column(
        index=True,
        nullable=False,
        comment="Associated repository data source ID",
    )

    pr_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Provider-native pull request number (e.g. Bitbucket PR id / GitHub PR number)",
    )

    title: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Pull request title",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Pull request description / body",
    )

    author_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Display name of the pull request author",
    )
    author_email: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment="Email of the pull request author (if available)",
    )

    source_branch: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Name of the source branch that was merged (e.g. feature/PROJ-1234_ShortDescription)",
    )
    target_branch: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Target branch the pull request was merged into",
    )

    merged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp the pull request was merged; used to order file revisions",
    )

    issue_key: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Child issue key this pull request is associated with (e.g. the Jira/GitHub issue referenced by its source branch)",
    )

    url: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment="Web URL to the pull request",
    )

    # Relationships
    project_repo_summary: Mapped["ProjectRepoSummary"] = relationship(
        back_populates="pull_requests",
    )

    file_pr_diffs: Mapped[List["ProjectFileDiff"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
    )

    commits: Mapped[List["GitCommit"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
    )
