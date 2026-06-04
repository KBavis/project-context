from __future__ import annotations
import logging
import httpx
from abc import ABC, abstractmethod

from .base import IssueTrackerDataProvider
from app.core import settings

logger = logging.getLogger(__name__)


class JiraDataProvider(IssueTrackerDataProvider):
    """
    Data provider for interfacing with Jira. As of now, the main functionlity
    this provider is responsible for is resolving all the child stories/tasks
    for a given set of 'Epic' keys. This is something that is fairly unique 
    to Jira, so other IssueTrackerDataProvider implementations may just simply 
    return the set of configured IssueKeys set up on a given Project. 
    """
    def __init__(self, data_source):
        super().__init__(data_source=data_source)
        self.auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN) # TODO: Configure Authentication for Jira Data Provider


    def _validate_url(self, url: str):
        # TODO: Implement URL validation
        pass


    def _get_request_headers(self) -> dict[str, str] | None:
        # TODO: Implement request headers extraction
        return None


    async def get_issues(self, epics: list[str]) -> list[str]:
        """
        Find all stories/tasks linked to a given set of Epic Keys. 
        """

        if not epics:
            return []

        story_keys = []
        url = f"{self.url}/rest/api/3/search"


        # leverage JQL with the provided set of Epics to find child stories/tasks 
        try:

            # configure JQL query
            epics_jql = ", ".join([f'"{key}"' for key in epics])
            jql = f'"Epic Link" in ({epics_jql}) OR parent in ({epics_jql})'

            # configure initial payload for Jira Search API
            payload = {
                "jql": jql,
                "fields": ["key"], 
                "maxResults": 100,
                "startAt": 0
            }

            # configure client to be leveraged for pagination through Jira Search API results
            client = httpx.AsyncClient()

            try:

                # loop through paginated response if necessary  
                while True:

                    resposne = await client.post(url, json=payload, auth=self.auth, headers=self._get_request_headers())
                    response.raise_for_status()

                    # extract story keys from resposne 
                    data = response.json()
                    issues = data.get("issues", [])
                    for issue in issues:
                        story_keys.append(issue["key"])

                    # determine if there are additional results to fetch 
                    total = data.get("total", 0)
                    current_recieved = payload["startAt"] + len(issues)
                    if current_recieved >= total or not issues:
                        logger.info(f"Finished fetching linked stories for epics {epics}. Total stories found: {len(story_keys)}")
                        break
                    
                    # advance pointer for next batch of results
                    payload["startAt"] += payload["maxResults"]

            finally:
                await client.aclose() 
     
        except Exception as e:
            logger.error(f"Failure resolving Jira stories for epics {epics}: {str(e)}")
            
        return story_keys
