from abc import abstractmethod, ABC

class DataProvider(ABC):

    def __init__(self, url: str=""):
        self.url = url
        self.request_headers = self._get_request_headers()

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
    