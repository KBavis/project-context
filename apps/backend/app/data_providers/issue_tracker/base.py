from __future__ import annotations
from abc import abstractmethod
from app.data_providers.base import DataProvider

class IssueTrackerDataProvider(DataProvider):
    """
    Abstract base class for Issue Tracker data providers.
    """
    
    @abstractmethod
    async def get_issues(self, epics: list[str]) -> list[str]:
        """
        Resolves a list of Epic keys into their constituent child issues (e.g., Stories).
        """
        raise NotImplementedError()
