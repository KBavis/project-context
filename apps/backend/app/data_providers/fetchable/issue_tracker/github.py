from __future__ import annotations
import logging

from .base import IssueTrackerDataProvider

logger = logging.getLogger(__name__)


class GitHubIssueDataProvider(IssueTrackerDataProvider):
    """
    Data provider for interfacing with GitHub Issues.
    Unlike Jira, GitHub issues typically don't have a strict Epic/Story 
    parent-child relationship that we need to resolve via API queries.
    Instead, if a project is scoped by GitHub issues, the parent issues 
    provided are exactly the issues we care about.
    """
    def __init__(self, data_source):
        super().__init__(data_source=data_source)

    def _validate_url(self):
        pass

    def _get_request_headers(self) -> dict[str, str] | None:
        return None

    async def get_issues(self, parent_issues: list[str]) -> list[str]:
        """
        For GitHub, the 'parent_issues' (which might be full URLs or issue numbers)
        are returned as-is since they represent the exact issues we want to 
        track commits against.
        """
        if not parent_issues:
            return []
            
        logger.info(f"GitHubIssueDataProvider returning parent issues directly: {parent_issues}")
        return parent_issues
