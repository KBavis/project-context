from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .git_commit import GitCommitDetail


class PullRequestDetail(BaseModel):
    """
    Metadata for a single merged pull request linked to a project's issues.

    Diffs are fetched separately via ``get_pr_diff`` so PR resolution stays
    cheap; ``commits`` excludes merge commits (parents > 1).
    """

    pr_number: int
    title: str
    description: str | None = None
    author_name: str
    author_email: str | None = None
    source_branch: str
    """Name of the source branch that was merged (its display id)."""
    target_branch: str
    """Target branch the pull request was merged into (its display id)."""
    merged_at: datetime
    issue_key: str
    """Child issue key this pull request matched (e.g. via its source branch)."""
    url: str | None = None
    commits: list[GitCommitDetail] = []
    """Non-merge commits contained in the pull request (descriptive metadata)."""
