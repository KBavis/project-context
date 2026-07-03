class TaskSkipped(Exception):
    """Raised by a task body to signal a legitimate (non-error) skip."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)
