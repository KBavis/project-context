from __future__ import annotations

from pydantic import BaseModel

from .change_type import ChangeType


class FileDiffPatch(BaseModel):
    """
    A single file's diff as introduced by one pull request.

    The provider faithfully reports the per-file change; the diff sync job is
    responsible for mapping it onto ProjectAffectedFile /
    ProjectFileDiff rows (including treating renames as a delete at
    the old path + add at the new path).
    """

    file_path: str
    """Repo-relative destination path (source path when the file was deleted)."""

    previous_path: str | None = None
    """Old path when the file was renamed/moved within the pull request."""

    change_type: ChangeType

    unified_diff: str
    """Git-style unified diff text for this path only (headers + all hunks)."""

    truncated: bool = False
    """True when the provider reported the diff was truncated (e.g. too large)."""
