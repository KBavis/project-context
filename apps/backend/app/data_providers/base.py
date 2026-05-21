from __future__ import annotations
from uuid import UUID

from app.models.data_source import DataSource

from abc import abstractmethod, ABC
import logging
from app.services.file import FileService

logger = logging.getLogger(__name__)

class DataProvider(ABC):

    def __init__(self, data_source: DataSource, file_svc: FileService | None = None, job_pk: UUID | None = None):
        self.data_source = data_source
        self.job_pk = job_pk
        self.url = data_source.url
        self.file_svc = file_svc
        self.request_headers = self._get_request_headers()
    

    @classmethod 
    def from_provider(cls, data_source: DataSource, file_svc: FileService | None = None, job_pk: UUID | None = None):
        match data_source.provider:
            case "GitHub":
                from app.data_providers.repository.github import GithubDataProvider
                return GithubDataProvider(data_source=data_source, file_svc=file_svc, job_pk=job_pk)
            case "Jira":
                from app.data_providers.issue_tracker.jira import JiraDataProvider
                return JiraDataProvider(data_source=data_source, file_svc=file_svc, job_pk=job_pk)
            case _:
                raise Exception(f"The specified Data Source provider is not configured for this application")
    

    @abstractmethod
    async def ingest_data(self):
        raise NotImplementedError()


    @abstractmethod
    def _validate_url(self, url: str):
        raise NotImplementedError()

    @abstractmethod
    def _get_request_headers(self) -> dict[str, str] | None:
        """Get request headers for API calls. Returns None if no auth is needed."""
        raise NotImplementedError()

    @abstractmethod
    async def view_file(self, file_path: str) -> str:
        """
        Functionality to extract exact file contents from a particular path 
        This function will end up being an internal tool that we can leverage in our "research" phase of 
        our Agentic Worfklow 

        Args:
            file_path (str): The absolute path to the file to view 
        """
        raise NotImplementedError()

    @abstractmethod
    async def list_directory(self, path: str) -> str:
        """
        Functionality to list the contents of a particular directory 
        This function will end up being an internal tool that we can leverage in our "research" phase of 
        our Agentic Worfklow 

        NOTE: Instead of having some massive "view_project_strucutre" tool, we can just use 
        the "list_directory" function based on retrieved files from our key word / sematnic search

        Args:
            path (str): The absolute path to the directory to list the contents of 
        """
        raise NotImplementedError()
    

    async def generate_citation(self, file_path: str) -> str: 
        """
        Generates a citation for a given file path 

        Args:
            file_path (str): The absolute path to the file to generate a citation for 
        
        Returns:
            str: The citation for the file
        """
        raise NotImplementedError()
        