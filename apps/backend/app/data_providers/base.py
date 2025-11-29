from sqlalchemy.orm import Session

from app.files import FileHandler
from app.models import DataSource

from abc import abstractmethod, ABC

class DataProvider(ABC):

    def __init__(self, file_service, data_source: DataSource, url: str = ""):
        self.data_source = data_source
        self.url = url
        self.request_headers = self._get_request_headers()
        self.file_handler = FileHandler(file_service)

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
