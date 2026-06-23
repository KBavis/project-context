from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, String, DateTime, Text, ARRAY, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .pull_request import PullRequest


class GitCommit(Base):
    """
    Descriptive metadata for a single non-merge commit that belongs to a merged
    pull request.

    Commits are persisted purely as descriptive context for a PullRequest; the
    actual per-file diffs are derived from the pull request diff, not from
    individual commits. Merge commits (parents > 1) are excluded.
    """

    __tablename__ = "git_commit"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        index=True,
        server_default=text("gen_random_uuid()"),
    )

    pull_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("pull_request.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="The pull request this commit belongs to",
    )

    commit_hash: Mapped[str] = mapped_column(
        String,
        index=True,
        nullable=False,
        comment="Commit SHA-1 hash",
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

    # Relationships
    pull_request: Mapped["PullRequest"] = relationship(
        back_populates="commits",
    )
