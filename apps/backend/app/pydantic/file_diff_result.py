from pydantic import BaseModel


class FileDiffResult(BaseModel):
    """
    Composite diff result for a single file across all cherry-picked project commits.
    """
    file_path: str
    unified_diff: str | None
    """Unified diff text (None when conflict_detected=True and recovery also failed)."""

    diff_hash: str
    """sha256 hex of unified_diff bytes; empty string when unified_diff is None."""

    diff_truncated: bool = False
    """True if the unified_diff was capped at MAX_DIFF_BYTES."""

    conflict_detected: bool = False
    """
    True if at least one cherry-pick could not be applied cleanly even after
    whitespace-tolerant and 3-way-merge fallbacks.  The diff may still be
    partially populated if some commits applied successfully.
    """

    failed_commit_shas: list[str] = []
    """SHAs that could not be applied; useful for diagnostics / re-try logic."""
