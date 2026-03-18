from __future__ import annotations
from uuid import UUID

from app.models.data_source import DataSource
from app.services.file import FileService

from abc import abstractmethod, ABC
import logging

logger = logging.getLogger(__name__)

class DataProvider(ABC):

    def __init__(self, data_source: DataSource, job_pk: UUID, file_svc: FileService):
        self.data_source = data_source
        self.job_pk = job_pk
        self.url = data_source.url
        self.file_svc = file_svc
        self.request_headers = self._get_request_headers()
    

    @abstractmethod
    async def ingest_data(self):
        pass

    @abstractmethod
    async def _download_file(self, url: str, headers: dict = {}):
        pass

    @abstractmethod
    def _validate_url(self, url: str):
        pass

    @abstractmethod
    def _get_request_headers(self) -> dict[str, str] | None:
        """Get request headers for API calls. Returns None if no auth is needed."""
        pass
