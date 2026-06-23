from __future__ import annotations

from enum import Enum


class ChangeType(Enum):
    """
    The effect a change has on a file path.
    """

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    UNKNOWN = "unknown"
