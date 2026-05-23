from __future__ import annotations

import logging
from uuid import UUID
from abc import abstractmethod

from app.models import DataSource
from app.services.file import FileService
from app.data_providers import DataProvider
from app.data_providers.base import Provider
from pathlib import Path
from io import BytesIO


class IngestibleDataProvider(DataProvider):
    def __init__(
        self, 
        data_source: DataSource
    ) -> None:
        super().__init__(data_source=data_source)
        self.file_svc: FileService | None = None
        self.job_pk: UUID | None = None

    @classmethod
    def from_provider(cls, data_source: DataSource) -> IngestibleDataProvider:
        match data_source.provider:
            case Provider.GITHUB:
                from app.data_providers.ingestible.repository.github import GithubDataProvider
                return GithubDataProvider(data_source=data_source)
            case _:
                raise Exception(f"Data Source provider {data_source.provider} is not configured as an Ingestible Data Provider")
    
    @abstractmethod
    async def ingest_data(self, job_pk: UUID, file_svc: FileService):
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

    def _write_file(self, full_path: Path, buffer: BytesIO):
        """Sync helper: write buffered content to disk (runs in worker thread)."""
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(buffer.getbuffer())

    async def generate_citation(self, file_path: str) -> str: 
        """
        Generates a citation for a given file path 

        Args:
            file_path (str): The absolute path to the file to generate a citation for 
        
        Returns:
            str: The citation for the file
        """
        raise NotImplementedError()