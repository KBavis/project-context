from enum import Enum



class ProcessingStatus(Enum):
    """
    Class to represent the status of an ongoing process
    """
    SUCCESS = "success"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"