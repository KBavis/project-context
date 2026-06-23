from __future__ import annotations
from abc import abstractmethod
from uuid import UUID
from datetime import datetime

from app.data_providers.ingestible.base import IngestibleDataProvider
from app.data_providers import Provider
from app.models.data_source import DataSource
from app.services.file import FileService
from app.pydantic.pull_request import PullRequestDetail
from app.pydantic.file_diff_patch import FileDiffPatch

if TYPE_CHECKING:
    from app.data_providers.fetchable.issue_tracker.base import IssueTrackerDataProvider

logger = logging.getLogger(__name__)

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
            case Provider.BITBUCKET:
                from app.data_providers.ingestible.repository.bitbucket import BitbucketDataProvider
                return BitbucketDataProvider(data_source=data_source)
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
    async def resolve_prs(
        self,
        issue_keys: list[str],
        issue_provider: IssueTrackerDataProvider,
    ) -> list[PullRequestDetail]:
        """
        Resolve the merged pull requests linked to a set of issue keys.

        ``issue_provider`` is the project's issue tracker. Providers that resolve
        the issue<->pull-request linkage natively use it (e.g. Bitbucket resolves
        PRs through Jira's dev-status API rather than scanning Bitbucket); other
        providers may match locally and ignore it. Only MERGED pull requests
        targeting this data source's branch are returned. The returned commit
        metadata excludes merge commits (parents > 1).
        """
        raise NotImplementedError()

    @abstractmethod
    async def get_pr_diff(self, pr_number: int) -> list[FileDiffPatch]:
        """
        Return the per-file diffs introduced by a single pull request.

        Each entry is one file's unified diff for this pull request (the
        provider-native three-dot diff: merge-base(target, source)..source).
        Renames are reported with ``previous_path`` set so the caller can treat
        them as a delete at the old path + add at the new path.
        """
        raise NotImplementedError()
        
