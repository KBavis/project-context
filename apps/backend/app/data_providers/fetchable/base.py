from __future__ import annotations

from app.models import DataSource
from app.data_providers import DataProvider
from app.models.data_source import DataSourceType

class FetchableDataProvider(DataProvider):
    def __init__(
        self, 
        data_source: DataSource
    ) -> None:
        super().__init__(data_source=data_source)

    @classmethod
    def from_provider(cls, data_source: DataSource) -> FetchableDataProvider:
        match data_source.type:
            case DataSourceType.ISSUE_TRACKER:
                from app.data_providers.fetchable.issue_tracker import IssueTrackerDataProvider
                return IssueTrackerDataProvider.from_provider(data_source)
            case _:
                raise Exception(f"Data Source type {data_source.type} is not configured as a Fetchable Data Provider")
