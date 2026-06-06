from __future__ import annotations
from abc import abstractmethod
from app.data_providers.fetchable import FetchableDataProvider

class IssueTrackerDataProvider(FetchableDataProvider):
    """
    Abstract base class for Issue Tracker data providers.
    """
    
    @abstractmethod
    async def get_issues(self, parent_issues: list[str]) -> list[str]:
        """
        Resolves a list of Parent Issue keys into their constituent child issues (e.g., Stories). Some 
        IssueTrackers may not have the aspect of parent_issues, in which case, the parent 
        issues themselves ARE the child issues 
        """
        raise NotImplementedError()
