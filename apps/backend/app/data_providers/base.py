from __future__ import annotations
from uuid import UUID
from enum import Enum

from app.models.data_source import DataSource

from abc import abstractmethod, ABC
import logging

logger = logging.getLogger(__name__)


class Provider(str, Enum):
    GITHUB = "GitHub"
    JIRA = "Jira"


class DataProvider(ABC):

    def __init__(self, data_source: DataSource):
        self.data_source = data_source
        self.url = data_source.url
        self.request_headers = self._get_request_headers()
    

    @classmethod 
    def from_provider(cls, data_source: DataSource):
        match data_source.provider:
            case Provider.GITHUB:
                from app.data_providers.ingestible.repository.github import GithubDataProvider
                return GithubDataProvider(data_source=data_source)
            case Provider.JIRA:
                from app.data_providers.fetchable.issue_tracker.jira import JiraDataProvider
                return JiraDataProvider(data_source=data_source)
            case _:
                raise Exception(f"The specified Data Source provider is not configured for this application")
    
    @abstractmethod
    def _validate_url(self, url: str):
        raise NotImplementedError()

    @abstractmethod
    def _get_request_headers(self) -> dict[str, str] | None:
        """Get request headers for API calls. Returns None if no auth is needed."""
        raise NotImplementedError()
