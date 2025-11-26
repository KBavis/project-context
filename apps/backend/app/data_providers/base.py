from sqlalchemy.orm import Session

from app.files import FileHandler
from app.models import DataSource

import logging

from abc import abstractmethod, ABC
from enum import Enum

class FileProcessStatus(Enum):

    UNCHANGED = "unchanged"
    UPDATED = "updated"
    CREATED = "created"
    MOVED = "moved"
    COPIED = "copied"


logger = logging.getLogger(__name__)

class DataProvider(ABC):

    def __init__(self, db: Session, data_source: DataSource, url: str = ""):
        self.data_source = data_source
        self.url = url
        self.request_headers = self._get_request_headers()
        self.file_handler = FileHandler(db)

    @abstractmethod
    def ingest_data():
        pass

    @abstractmethod
    def _download_file(url: str, headers: dict = {}):
        pass

    @abstractmethod
    def _validate_url(url: str):
        pass

    @abstractmethod
    def _get_request_headers(self):
        pass
