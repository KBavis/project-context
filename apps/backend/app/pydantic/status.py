from __future__ import annotations
from enum import Enum



class ProcessingStatus(Enum):
    """
    Class to represent the status of an ongoing process
    """
    SUCCESS = "success"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_YET_SYNCED = "not_yet_synced"