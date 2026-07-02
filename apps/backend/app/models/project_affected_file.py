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
    from .diff_task import DiffTask
    from .project_repo_summary import ProjectRepoSummary
    from .project_file_diff import ProjectFileDiff


class ProjectAffectedFile(Base):
    """
    A single file's change history produced by one project on one repository
    DataSource.
    """

    __tablename__ = "project_affected_file"

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "data_source_id"],
            [
                "project_repo_summary.project_id",
                "project_repo_summary.data_source_id",
            ],
            deferrable=True,  # only enforce the constraint at transaction commit
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "project_id",
            "data_source_id",
            "file_path",
            name="uq_project_affected_file_path",
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

    last_diff_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("diff_task.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        comment="Job that last wrote this row; used to determine last time this path was synced",
    )

    project_repo_summary: Mapped["ProjectRepoSummary"] = relationship(
        back_populates="file_histories",
    )
    diff_task: Mapped["DiffTask"] = relationship()

    pr_diffs: Mapped[List["ProjectFileDiff"]] = relationship(
        back_populates="file_history",
        cascade="all, delete-orphan",
        order_by="ProjectFileDiff.ordinal",
    )
