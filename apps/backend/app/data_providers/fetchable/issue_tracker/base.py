from __future__ import annotations
from abc import abstractmethod

from app.data_providers.fetchable import FetchableDataProvider
from app.data_providers.base import Provider
from app.models.data_source import DataSource

class IssueTrackerDataProvider(FetchableDataProvider):
    """
    Abstract base class for Issue Tracker data providers.
    """

    @classmethod
    def from_provider(cls, data_source: DataSource) -> IssueTrackerDataProvider:
        match data_source.provider:
            case Provider.JIRA:
                from app.data_providers.fetchable.issue_tracker.jira import JiraDataProvider
                return JiraDataProvider(data_source=data_source)
            case Provider.GITHUB:
                from app.data_providers.fetchable.issue_tracker.github import GitHubIssueDataProvider
                return GitHubIssueDataProvider(data_source=data_source)
            case _:
                raise Exception(f"Data Source provider {data_source.provider} is not configured as a Issue Tracker Data Provider")

    
    @abstractmethod
    async def get_issues(self, parent_issues: list[str]) -> list[str]:
        """
        Resolves a list of Parent Issue keys into their constituent child issues (e.g., Stories). Some 
        IssueTrackers may not have the aspect of parent_issues, in which case, the parent 
        issues themselves ARE the child issues 
        """
        raise NotImplementedError()
