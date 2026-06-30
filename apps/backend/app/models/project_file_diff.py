from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from app.pydantic.change_type import ChangeType

if TYPE_CHECKING:
    from .project_affected_file import ProjectAffectedFile
    from .pull_request import PullRequest


class ProjectFileDiff(Base):
    """
    A single file's diff as introduced by one merged pull request.

    A file's history (``ProjectAffectedFile``) is the ordered list of
    these per-PR diffs (one per pull request that touched the path). The list is
    sequential — NOT a netted composite — so the LATEST diff is the most recent
    change to the path, not the cumulative effect of the project. Consumers
    reason across the ordered diffs to derive net state.
    """

    __tablename__ = "project_file_diff"

    __table_args__ = (
        UniqueConstraint(
            "file_history_id",
            "pull_request_id",
            name="uq_project_file_diff_history_pr",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        index=True,
        server_default=text("gen_random_uuid()"),
    )

    file_history_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_affected_file.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="The file history this per-PR diff belongs to",
    )
    pull_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("pull_request.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="The merged pull request that introduced this diff",
    )

    ordinal: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="0-based position of this diff within the file's ordered history "
                "(ascending by pull request merge time)",
    )

    change_type: Mapped[ChangeType] = mapped_column(
        SQLAlchemyEnum(ChangeType, name="change_type_enum"),
        nullable=False,
        comment="This pull request's effect on the path (added | modified | deleted)",
    )

    unified_diff: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Git unified diff for this path as introduced by this pull request",
    )
    diff_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="sha256 hex of bytes stored in unified_diff (after cap); used to skip re-embed",
    )
    diff_truncated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True if unified_diff was capped",
    )

    # Relationships
    file_history: Mapped["ProjectAffectedFile"] = relationship(
        back_populates="pr_diffs",
    )
    pull_request: Mapped["PullRequest"] = relationship(
        back_populates="file_pr_diffs",
    )
