from __future__ import annotations
from abc import abstractmethod
from uuid import UUID
from datetime import datetime

from app.data_providers.ingestible.base import IngestibleDataProvider
from app.data_providers import Provider
from app.models.data_source import DataSource
from app.services.file import FileService
from app.pydantic.git_commit import GitCommitDetail

class RepositoryDataProvider(IngestibleDataProvider):
    """
    Abstract base class for Repository data providers (like GitHub, BitBucket, etc).
    Contains methods specific to pulling source code and PR diffs.
    """

    def __init__(self, data_source: DataSource):
        super().__init__(data_source=data_source)

        # validate URL is in expected format for Repository 
        self._validate_url()

        # extract relevant from URL & data source
        repository_owner, repository_name = self._parse_repository_ref()
        self._repository_name = repository_name
        self._branch_name = data_source.branch
        self._repository_owner = repository_owner

        # construct requried URLs
        self._construct_base_urls()


    @classmethod
    def from_provider(cls, data_source: DataSource) -> RepositoryDataProvider:
        match data_source.provider:
            case Provider.GITHUB:
                from app.data_providers.ingestible.repository import GithubDataProvider
                return GithubDataProvider(data_source=data_source)
            case _:
                raise Exception(f"Data Source provider {data_source.provider} is not configured as a Repository Data Provider")


    @property
    def repository_owner(self) -> str:
        """
        The username of the repository owner.
        """
        return self._repository_owner

    @property
    def repository_name(self) -> str:
        """
        The name of the repository.
        """
        return self._repository_name

    @property
    def branch_name(self) -> str:
        """
        The name of the branch.
        """
        return self._branch_name

    @property
    def full_name(self) -> str:
        """
        Full name of repository (owner & repo name)
        """
        return f"{self._repository_owner}/{self._repository_name}"
    

    @abstractmethod
    def _parse_repository_ref(self) -> tuple[str, str]:
        """
        Extract (repository_owner, repository_name) from provided Data Source URL 
        """
        raise NotImplementedError()
    
    @abstractmethod
    def _construct_base_urls(self):
        """
        Construct the base URLs for the repository.
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
    

    @abstractmethod
    async def get_all_commits_info(self, child_issues: list[str], latest_commit_date: datetime | None = None) -> list[GitCommitDetail]:
        """
        Get all commit details. Optionally provide the `latest_commit_date` to retrieve any 
        commits found since the last commit that we ingested.
        """
        raise NotImplementedError()


    @abstractmethod
    async def get_commit_detail(self, sha: str) -> GitCommitDetail:
        """
        Get details for a specific commit.
        """
        raise NotImplementedError()


    @abstractmethod
    async def get_latest_commit_sha(self, child_issues: list[str]) -> str | None:
        """
        Get the latest commit SHA for the repository.
        """
        raise NotImplementedError()
        
