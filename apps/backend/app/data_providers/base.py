from __future__ import annotations
from enum import Enum

from app.models.data_source import DataSource, DataSourceType

from abc import abstractmethod, ABC
import logging

logger = logging.getLogger(__name__)


class Provider(str, Enum):
    GITHUB = "GitHub"
    JIRA = "Jira"
    BITBUCKET = "BitBucket"
    CONFLUENCE = "Confluence"


class DataProvider(ABC):

    def __init__(self, data_source: DataSource):
        self.data_source = data_source
        self.url = data_source.url
        self.request_headers = self._get_request_headers()
    

    @classmethod 
    def from_provider(cls, data_source: DataSource):
        match data_source.type:
            case DataSourceType.ISSUE_TRACKER:
                from app.data_providers.fetchable.issue_tracker.base import IssueTrackerDataProvider
                return IssueTrackerDataProvider.from_provider(data_source)
            case DataSourceType.REPOSITORY:
                from app.data_providers.ingestible.repository.base import RepositoryDataProvider
                return RepositoryDataProvider.from_provider(data_source)
            case _:
                raise Exception(
                    f"The specified Data Source type {data_source.type} is not configured for this application"
                )
    
    @abstractmethod
    def _validate_url(self):
        """
        Validate the given URL corresponds to the expected Data Provider
        """
        raise NotImplementedError()

    @abstractmethod
    def _get_request_headers(self) -> dict[str, str] | None:
        """Get request headers for API calls. Returns None if no auth is needed."""
        raise NotImplementedError()
