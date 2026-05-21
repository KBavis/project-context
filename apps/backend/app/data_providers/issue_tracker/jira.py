from __future__ import annotations
import logging
import httpx
from abc import ABC, abstractmethod

from .base import IssueTrackerDataProvider
from app.core import settings

logger = logging.getLogger(__name__)


class JiraDataProvider(IssueTrackerDataProvider):
    """
    Implementation of IssueTrackerDataProvider for Jira.
    """
    def __init__(self, data_source, file_svc=None, job_pk=None, base_url: str = "", email: str = "", api_token: str = ""):
        super().__init__(data_source, file_svc, job_pk)
        # Assuming URL/creds are passed or retrieved from data_source metadata
        self.base_url = base_url.rstrip("/") if base_url else data_source.url.rstrip("/")
        # Note: in real implementation, email/api_token might come from Secrets Manager. 
        self.auth = (email, api_token)

    async def get_issues(self, epics: list[str]) -> list[str]:
        """
        Find all stories/tasks that are children of the provided Epic keys.
        Returns a list of Jira issue keys (e.g., ["PROJ-101", "PROJ-102"]).
        """
        if not epics:
            return []

        story_keys = []
        try:
            # JQL to find all issues linked to the given epics
            epics_jql = ", ".join([f'"{key}"' for key in epics])
            jql = f'"Epic Link" in ({epics_jql}) OR parent in ({epics_jql})'
            
            url = f"{self.base_url}/rest/api/3/search"
            params = {
                "jql": jql,
                "fields": "key",
                "maxResults": 100
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, auth=self.auth)
                response.raise_for_status()
                data = response.json()
                
                for issue in data.get("issues", []):
                    story_keys.append(issue["key"])
                    
        except Exception as e:
            logger.error(f"Failure resolving Jira stories for epics {epics}: {str(e)}")
            
        return story_keys
