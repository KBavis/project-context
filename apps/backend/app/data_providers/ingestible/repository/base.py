from __future__ import annotations
from abc import abstractmethod
from uuid import UUID
from app.data_providers.ingestible.base import IngestibleDataProvider
from app.services.file import FileService

class RepositoryDataProvider(IngestibleDataProvider):
    """
    Abstract base class for Repository data providers (like GitHub, BitBucket, etc).
    Contains methods specific to pulling source code and PR diffs.
    """
    
    @abstractmethod
    async def resolve_prs(self, story_keys: list[str]) -> list[int]:
        """
        Find PRs associated with the provided issue tracker story keys.
        """
        raise NotImplementedError()
        
    @abstractmethod
    async def get_pr_diff(self, pr_number: int) -> str:
        """
        Get the unified diff for a specific PR.
        """
        raise NotImplementedError()
        
    @abstractmethod
    async def _get_repository_data(self, curr_url: str, file_svc: FileService, job_pk: UUID):
        """
        Recursively pull down the repository contents.
        """
        raise NotImplementedError()
        
    @abstractmethod
    async def _download_file(self, url: str, file_name: str, file_path: str, size: int, file_svc: FileService, job_pk: UUID):
        """
        Download a file to the temporary directory.
        """
        raise NotImplementedError()
        
