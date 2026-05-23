from __future__ import annotations

import logging
from uuid import UUID
from abc import abstractmethod

from app.models import DataSource
from app.data_providers import DataProvider
from app.data_providers.base import Provider

class FetchableDataProvider(DataProvider):
    def __init__(
        self, 
        data_source: DataSource
    ) -> None:
        super().__init__(data_source=data_source)

    @classmethod
    def from_provider(cls, data_source: DataSource) -> FetchableDataProvider:
        match data_source.provider:
            case Provider.JIRA:
                from app.data_providers.fetchable.issue_tracker.jira import JiraDataProvider
                return JiraDataProvider(data_source=data_source)
            case _:
                raise Exception(f"Data Source provider {data_source.provider} is not configured as a Fetchable Data Provider")
