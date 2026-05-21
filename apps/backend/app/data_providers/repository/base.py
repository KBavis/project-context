from __future__ import annotations
from abc import abstractmethod
from app.data_providers.base import DataProvider

class RepositoryDataProvider(DataProvider):
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
    async def _get_repository_data(self, curr_url: str):
        """
        Recursively pull down the repository contents.
        """
        raise NotImplementedError()
        
    @abstractmethod
    async def _download_file(self, url: str, file_name: str, file_path: str, size: int):
        """
        Download a file to the temporary directory.
        """
        raise NotImplementedError()
        
    @abstractmethod
    def _write_file(self, full_path, buffer):
        """
        Write buffered file content to disk.
        """
        raise NotImplementedError()
